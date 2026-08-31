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
import time
from collections.abc import Callable

from app.queue import EventQueue, Message, ReceiptHandleIsInvalid
from app.stores import EventIndex, EventStore

log = logging.getLogger(__name__)

# Distinct events failing back to back is not a message problem. One poison event fails
# repeatedly, but the deliveries around it succeed; when *different* events fail in an
# unbroken run, the thing that is broken is downstream of all of them.
SINK_FAILURE_THRESHOLD = 3
# Doubling, and capped. The pause is never shorter than what the queue's own backoff
# already imposes, so opening the circuit cannot make a message dead-letter sooner than
# it would have - it only stops the rest of the backlog from burning deliveries beside it.
SINK_PAUSE_SECONDS = 5.0
# The ceiling is the visibility timeout, not a number picked for feeling right. Probing
# more often than that cannot help - a message that failed is not visible again any
# sooner - and probing less often only delays recovery, because the pause is also how long
# the worker keeps sleeping after the outage has ended. The worker passes its own timeout
# in; this default exists for a circuit built without one.
SINK_MAX_PAUSE_SECONDS = 30.0


class SinkCircuit:
    """Whether the stores are answering, and therefore whether to pull more work.

    This is the fix for the defect §6 had already quantified and not defended against.
    The queue dead-letters a message after `max_receives` deliveries, which with the
    default backoff puts the last one at **930 seconds**: MongoDB down for about fifteen
    minutes and every event in flight is dead-lettered as poison, when nothing was wrong
    with any of them. The queue cannot tell the difference, because from where it sits
    there is none - it sees a delivery that produced no delete.

    The consumer can. *This message fails* and *everything fails right now* look identical
    one message at a time and completely different across several, so the worker stops
    pulling work it has just been shown it cannot do, and probes with a single message
    instead of a full batch.

    **This is not the retry logic CLAUDE.md forbids here, and the distinction is the
    point.** Nothing is caught in order to be tried again: a failed write still reaches no
    `delete`, and the message still comes back on the queue's own timetable, with the
    queue's own counter. What changes is only how much work this consumer accepts while
    the sinks are refusing it. Retry is the queue's; admission is the consumer's.

    Not thread-safe and it does not need to be. The consumers are asyncio tasks on one
    event loop and every method here runs to completion without awaiting, so no two can
    interleave inside one.
    """

    def __init__(
        self,
        *,
        threshold: int = SINK_FAILURE_THRESHOLD,
        pause: float = SINK_PAUSE_SECONDS,
        max_pause: float = SINK_MAX_PAUSE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._pause = pause
        self._max_pause = max_pause
        self._clock = clock
        self._failures: set[str] = set()
        self._open_until: float | None = None
        self._pauses = 0
        self._probing = False

    @property
    def is_open(self) -> bool:
        return self._open_until is not None

    def seconds_remaining(self) -> float:
        if self._open_until is None:
            return 0.0
        return max(0.0, self._open_until - self._clock())

    def allowance(self, batch_size: int) -> int:
        """How many messages this consumer may take now. `0` means wait.

        Half-open is one message, not one batch, and single-flight: eight consumers each
        probing with ten messages would burn eighty deliveries to answer a question one
        message answers.
        """
        if self._open_until is None:
            return batch_size
        if self._clock() < self._open_until or self._probing:
            return 0
        self._probing = True
        return 1

    def abandon_probe(self) -> None:
        """The probe found an empty queue. Release it, or nobody probes again."""
        self._probing = False

    def record_success(self) -> None:
        if self._open_until is not None:
            log.warning(
                "the sinks are answering again after %d paused cycle(s); resuming",
                self._pauses,
            )
        self._failures.clear()
        self._open_until = None
        self._probing = False
        self._pauses = 0

    def record_failure(self, event_id: str) -> None:
        self._probing = False
        self._failures.add(event_id)
        # Already paused, and a straggler from before the pause is not new evidence.
        # Without this the eight consumers that fail together at the onset of an outage
        # would each escalate the backoff and jump it straight to the cap.
        if self._open_until is not None and self._clock() < self._open_until:
            return
        if len(self._failures) < self._threshold:
            return
        self._pauses += 1
        delay = min(self._pause * 2 ** (self._pauses - 1), self._max_pause)
        self._open_until = self._clock() + delay
        log.error(
            "%d distinct events failed in a row: the sinks look unavailable, not the "
            "events. Pausing consumption for %gs so the backlog stops burning delivery "
            "attempts it cannot spend. Queue depth will grow, and /health will say so.",
            len(self._failures),
            delay,
        )


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
        visibility_timeout: float = 30.0,
        circuit: SinkCircuit | None = None,
    ) -> None:
        self._queue = queue
        self._store = store
        self._index = index
        self._concurrency = concurrency
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        # Not the queue's business to tell us: the worker asks for the window it needs,
        # which is what a consumer does in SQS too.
        self._visibility = visibility_timeout

        # One circuit for all N consumers. Per-consumer would need N times the evidence
        # to reach the same conclusion about a single shared dependency, which is exactly
        # the wrong way round: the whole signal is that the failures are not isolated.
        self._sink = circuit or SinkCircuit(max_pause=visibility_timeout)

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

    def reset_counters(self) -> None:
        """Zero the lifetime counters. Demo affordance only.

        In production these should be monotonic and never reset from the outside: a
        counter that can go down breaks every rate calculation built on top of it, which
        is why Prometheus-style counters only increase and consumers derive rates from
        differences. The demo reset is the one context where "start from a clean slate"
        is the whole point, and it exists only when DEMO_MODE is on.

        Deliberately not part of any interface the application depends on - the API
        reaches for it by name from the one route that is allowed to.
        """
        self._processed = 0
        self._failed = 0

    def stats(self) -> dict[str, object]:
        return {
            "processed": self._processed,
            # A paused worker and an idle one both report zero throughput, and only one of
            # them is a problem. Without this the console would show a queue filling with
            # a healthy worker beside it and no way to tell that the worker had stopped
            # pulling on purpose.
            "paused": self._sink.is_open,
            "resumes_in": round(self._sink.seconds_remaining(), 1),
            # Attempts, not events, and the name has to say so. Beside `processed` a bare
            # `failed` reads as "events that failed", and one poison message inflates it
            # by five - an operator could not tell one bad event from five lost ones. The
            # count of events that gave up permanently is `dlq`, reported by the queue.
            "failed_attempts": self._failed,
            "consumers": len(self._tasks),
        }

    # ---- internal -----------------------------------------------------------

    async def _loop(self, worker_id: int) -> None:
        while not self._stopping.is_set():
            # Ask before pulling. While the sinks are down this is 0 for every consumer
            # but the one holding the probe, and the backlog waits in the queue - visible,
            # counted by /health, and spending no delivery attempts.
            allowance = self._sink.allowance(self._batch_size)
            if allowance == 0:
                await asyncio.sleep(self._poll_interval)
                continue

            try:
                messages = await self._queue.receive(max_n=allowance)
            except Exception:
                # A failure reading the queue must not kill the consumer: if it dies,
                # nobody revives it and the queue grows silently.
                self._sink.abandon_probe()
                log.exception("worker-%d: failed to read from the queue", worker_id)
                await asyncio.sleep(self._poll_interval)
                continue

            if not messages:
                # An empty queue answers nothing about the sinks, so the probe is returned
                # rather than spent. Held, it would be held forever: nothing else releases
                # it, and consumption would never resume.
                self._sink.abandon_probe()
                await asyncio.sleep(self._poll_interval)
                continue

            for message in messages:
                await self._handle(message, worker_id)

    async def _handle(self, message: Message, worker_id: int) -> None:
        event = message.event
        try:
            # Claim the full window before starting, which is what the heartbeat is for.
            #
            # `receive` stamps one deadline across the whole batch, and the batch is
            # processed serially, so the last message of ten inherits a clock that started
            # nine writes ago. With a slow dependency the tail expires without ever having
            # been attempted: another consumer picks it up with the delivery count already
            # incremented, both work on it, and this one's delete is rejected as a stale
            # handle. Retries get burned in exactly the conditions where retries matter.
            #
            # Extending here costs one dictionary write and makes the message's window
            # start when work on it starts. The port defined this verb and nothing outside
            # a test ever called it.
            await self._queue.change_visibility(message.receipt_handle, self._visibility)
            # MongoDB FIRST, always.
            await self._store.upsert(event)
            await self._index.index(event)
            # Both writes landed, so whatever the circuit believed, it was wrong or is now
            # stale. Recorded before the delete: the delete can fail on a stale handle,
            # which says nothing about the sinks.
            self._sink.record_success()
        except Exception:
            self._failed += 1
            self._sink.record_failure(event.event_id)
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
