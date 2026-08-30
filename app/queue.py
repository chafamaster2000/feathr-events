"""The event queue: the port and its in-memory adapter.

The port deliberately exposes SQS's verbs. If the interface speaks the destination's
language, migrating to a real broker is ONE adapter, and the migration notes write
themselves:

    send(event)                       -> SendMessage
    receive(max_n, visibility_timeout)-> ReceiveMessage
    delete(receipt_handle)            -> DeleteMessage      <- this IS the ack
    change_visibility(handle, secs)   -> ChangeMessageVisibility

The state machine has three places and four transitions:

    VISIBLE --receive()--> INVISIBLE --delete()------> (gone)
       ^                       |
       |                       +--timeout lapses-----> VISIBLE (receive_count += 1)
       +-----------------------+
                               +--count >= max-------> DEAD-LETTER QUEUE

The one thing to understand: **a retry is the absence of a delete**, not an action. If the
worker dies, nobody deletes anything, the deadline lapses and the message returns on its
own. That is why there is no retry logic in the worker: all of it lives here.

See ARCHITECTURE.md §4.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from app.models import Event

DEFAULT_VISIBILITY_TIMEOUT = 30.0
DEFAULT_MAX_RECEIVES = 5
DEFAULT_MAXSIZE = 10_000
# 15 minutes: beyond this the dead-letter queue is more useful than waiting longer.
BACKOFF_CAP_SECONDS = 900.0


class QueueError(Exception):
    """Base class for queue errors."""


class QueueFull(QueueError):
    """The queue reached its bound.

    Translated to a 429 by the API. An unbounded queue protects nothing: it grows until
    the process runs out of memory and takes everything queued with it.
    """


class ReceiptHandleIsInvalid(QueueError):
    """The handle does not correspond to any in-flight message.

    Same name as the SQS error, on purpose. It happens when a worker stalls, the message
    is redelivered to another, and the first one revives and tries to delete it late: its
    handle is no longer valid, so it cannot overwrite someone else's work.
    """


@dataclass(frozen=True, slots=True)
class Message:
    """An event lent to a consumer, with the receipt needed to return it."""

    event: Event
    receipt_handle: str
    receive_count: int


@dataclass(slots=True)
class _Entry:
    """A message's internal state. Never leaves this module."""

    event: Event
    receive_count: int = 0
    handle: str | None = None  # the live handle; None while VISIBLE
    deadline: float = 0.0  # when the loan expires


class EventQueue(Protocol):
    """The port. The API and the worker depend on this, not on the implementation."""

    async def send(self, event: Event) -> None: ...

    async def receive(
        self, max_n: int = 1, visibility_timeout: float | None = None
    ) -> list[Message]: ...

    async def delete(self, receipt_handle: str) -> None: ...

    async def change_visibility(self, receipt_handle: str, seconds: float) -> None: ...

    def stats(self) -> dict[str, int]: ...


class InMemoryEventQueue:
    """An in-process queue with SQS semantics.

    On concurrency: there are no locks, deliberately. Every method mutates state without
    an `await` in between, so under asyncio (single thread, context switches only at
    await points) each one is atomic with respect to other tasks. An `asyncio.Lock` here
    would be noise implying a danger that does not exist. If I/O is ever added inside
    these methods the property breaks and the lock becomes necessary.

    On sweeping: expired messages are recovered lazily, at the start of `receive()`,
    rather than by a background task. It is simpler (one fewer moving part),
    deterministic in tests, and happens exactly when it matters: nobody needs a message
    to become visible again if there is no consumer asking.
    """

    def __init__(
        self,
        *,
        visibility_timeout: float = DEFAULT_VISIBILITY_TIMEOUT,
        max_receives: int = DEFAULT_MAX_RECEIVES,
        maxsize: int = DEFAULT_MAXSIZE,
        clock=time.monotonic,
    ) -> None:
        self._visibility_timeout = visibility_timeout
        self._max_receives = max_receives
        self._maxsize = maxsize
        # Injectable: tests advance time instead of sleeping through it.
        self._clock = clock

        self._entries: dict[str, _Entry] = {}
        self._visible: deque[str] = deque()
        self._inflight: dict[str, str] = {}  # handle -> message_id
        self._dlq: list[Event] = []

    # ---- the port -----------------------------------------------------------

    async def send(self, event: Event) -> None:
        if len(self._entries) >= self._maxsize:
            raise QueueFull(f"the queue reached its bound of {self._maxsize} messages")
        message_id = uuid.uuid4().hex
        self._entries[message_id] = _Entry(event=event)
        self._visible.append(message_id)

    async def receive(
        self, max_n: int = 1, visibility_timeout: float | None = None
    ) -> list[Message]:
        self._sweep()

        out: list[Message] = []
        base = visibility_timeout if visibility_timeout is not None else self._visibility_timeout
        now = self._clock()

        while self._visible and len(out) < max_n:
            message_id = self._visible.popleft()
            entry = self._entries.get(message_id)
            if entry is None:  # deleted while queued
                continue

            entry.receive_count += 1
            # The backoff is not a separate mechanism: it is this timeout, growing.
            entry.deadline = now + min(base * 2 ** (entry.receive_count - 1), BACKOFF_CAP_SECONDS)
            # A new handle on EVERY delivery: it invalidates the previous one.
            entry.handle = uuid.uuid4().hex
            self._inflight[entry.handle] = message_id

            out.append(
                Message(
                    event=entry.event,
                    receipt_handle=entry.handle,
                    receive_count=entry.receive_count,
                )
            )
        return out

    async def delete(self, receipt_handle: str) -> None:
        message_id = self._inflight.pop(receipt_handle, None)
        if message_id is None:
            raise ReceiptHandleIsInvalid(f"unknown or expired handle: {receipt_handle[:12]}...")
        self._entries.pop(message_id, None)

    async def change_visibility(self, receipt_handle: str, seconds: float) -> None:
        message_id = self._inflight.get(receipt_handle)
        if message_id is None:
            raise ReceiptHandleIsInvalid(f"unknown or expired handle: {receipt_handle[:12]}...")
        self._entries[message_id].deadline = self._clock() + seconds

    # ---- observability ------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Queue depth is the most informative number in the system.

        Stable near 0 -> the worker outpaces ingestion.
        Growing       -> the worker is the bottleneck.
        """
        return {
            "visible": len(self._visible),
            "in_flight": len(self._inflight),
            "dlq": len(self._dlq),
        }

    def dead_letters(self) -> list[Event]:
        """Messages that exhausted their retries. Reviewed by hand, never auto-replayed."""
        return list(self._dlq)

    # ---- internal -----------------------------------------------------------

    def _sweep(self) -> None:
        """Return expired loans to VISIBLE, or route them to the dead-letter queue."""
        now = self._clock()
        expired = [h for h, mid in self._inflight.items() if self._entries[mid].deadline <= now]

        for handle in expired:
            message_id = self._inflight.pop(handle)
            entry = self._entries[message_id]
            entry.handle = None

            if entry.receive_count >= self._max_receives:
                self._dlq.append(entry.event)
                del self._entries[message_id]
            else:
                self._visible.append(message_id)
