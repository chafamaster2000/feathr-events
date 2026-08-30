"""The worker that consumes the queue and writes to the stores.

It is deliberately small. All retry, backoff and dead-letter logic lives in the queue
(see `app/queue.py`), not here. The worker knows how to do one thing:

    1. write to MongoDB        (the source of truth)
    2. write to Elasticsearch  (the derived index)
    3. only then, delete the message

Order matters. Reversed, a failure would leave a searchable document that does not
exist: a phantom result, worse than a missing one.

And there is no `except` that retries. If either write fails, the function simply never
reaches the `delete` — the message comes back on its own when its visibility timeout
lapses, with the counter incremented. **A retry is the absence of a delete.**
See ARCHITECTURE.md §4 and §6.
"""

from __future__ import annotations

import asyncio
import logging

from app.queue import EventQueue, Message, ReceiptHandleIsInvalid
from app.stores import EventIndex, EventStore

log = logging.getLogger(__name__)


class EventWorker:
    """N concurrent consumers over one shared queue.

    The concurrency is safe without coordination because the work is commutative: every
    event carries its own `timestamp`, the upsert is idempotent by `event_id`, and no
    event needs to look at another. That is why N workers are N times the throughput
    without a single lock. See ARCHITECTURE.md §5.
    """

    def __init__(
        self,
        queue: EventQueue,
        store: EventStore,
        index: EventIndex,
        *,
        concurrency: int = 8,
        batch_size: int = 10,
        poll_interval: float = 0.05,
    ) -> None:
        self._queue = queue
        self._store = store
        self._index = index
        self._concurrency = concurrency
        self._batch_size = batch_size
        self._poll_interval = poll_interval

        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._processed = 0
        self._failed = 0

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._tasks:
            raise RuntimeError("the worker is already running")
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._loop(i), name=f"worker-{i}") for i in range(self._concurrency)
        ]
        log.info("worker started with %d consumers", self._concurrency)

    async def stop(self, drain_timeout: float = 10.0) -> None:
        """Orderly shutdown: ask to stop first, cancel second.

        Without draining, in-flight messages stay invisible until their timeout lapses —
        delayed for no reason. With it, they finish what they had.
        """
        if not self._tasks:
            return
        self._stopping.set()
        _done, pending = await asyncio.wait(self._tasks, timeout=drain_timeout)
        for task in pending:
            task.cancel()
        if pending:
            log.warning("%d consumers did not drain in time; cancelled", len(pending))
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks = []
        log.info("worker stopped - processed=%d failed=%d", self._processed, self._failed)

    # ---- observability ------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "processed": self._processed,
            "failed": self._failed,
            "consumers": len(self._tasks),
        }

    # ---- internal -----------------------------------------------------------

    async def _loop(self, worker_id: int) -> None:
        while not self._stopping.is_set():
            try:
                messages = await self._queue.receive(max_n=self._batch_size)
            except Exception:
                # A failure reading the queue must not kill the consumer: if it dies,
                # nobody revives it and the queue grows silently.
                log.exception("worker-%d: failed to read from the queue", worker_id)
                await asyncio.sleep(self._poll_interval)
                continue

            if not messages:
                await asyncio.sleep(self._poll_interval)
                continue

            for message in messages:
                await self._handle(message, worker_id)

    async def _handle(self, message: Message, worker_id: int) -> None:
        event = message.event
        try:
            # MongoDB FIRST, always.
            await self._store.upsert(event)
            await self._index.index(event)
        except Exception:
            self._failed += 1
            log.warning(
                "worker-%d: failed processing %s (attempt %d) - it will return by timeout",
                worker_id,
                event.event_id,
                message.receive_count,
                exc_info=True,
            )
            return  # no delete: the message comes back on its own

        try:
            await self._queue.delete(message.receipt_handle)
        except ReceiptHandleIsInvalid:
            # We took longer than the visibility timeout and the message was already
            # redelivered to another consumer. Not an error: both writes are idempotent,
            # so the duplicated work is harmless. Logged because it means the timeout is
            # too short for the real load.
            log.info(
                "worker-%d: %s was redelivered while we were processing it "
                "(the visibility timeout is too short)",
                worker_id,
                event.event_id,
            )
            return

        self._processed += 1
