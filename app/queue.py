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

import logging
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

# The dead-letter is bounded too. It used to be an unbounded list, and dead-lettering
# frees the entry it came from, so a sustained downstream outage could push every
# accepted event into a structure that counts against nothing and never stops growing -
# in a queue whose own docstring argues that an unbounded queue protects nothing. A
# deque that drops its oldest is the honest failure: bounded memory, and a log line
# naming what was discarded.
DLQ_MAXLEN = 1_000


class QueueError(Exception):
    """Base class for queue errors."""


log = logging.getLogger(__name__)


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

    async def fail(self, receipt_handle: str) -> None: ...

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
        self._dlq: deque[Event] = deque(maxlen=DLQ_MAXLEN)

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
            # The PROCESSING WINDOW, not the retry delay. These used to be the same number
            # and that was a real defect: the worker heartbeats the window at the start of
            # every delivery - it has to, or the tail of a batch inherits a clock that
            # started nine writes ago - and the heartbeat silently overwrote the grown
            # deadline this line used to set. Measured on the composed system, the gaps
            # between attempts were [30, 30, 30, 30] where the document claimed
            # [30, 60, 120, 240, 480]. The backoff was computed and then thrown away on
            # every single delivery.
            #
            # So the two are now separate, which is also what §4 already said this design
            # got wrong: "the growing timeout conflates two different things: how long a
            # consumer is allowed to process a message, and how long to wait before trying
            # again. A message on its fifth attempt that fails in five seconds still sits
            # invisible for the remaining 475." It does not any more. `fail()` sets the
            # retry delay when the outcome is known.
            entry.deadline = now + base
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

    async def fail(self, receipt_handle: str) -> None:
        """The consumer tried and could not. Hold the message for its backoff.

        The number stays here, in the queue, because retry policy is the queue's and not
        the worker's - the worker reports an outcome, it does not choose a delay. That is
        the same boundary `delete` sits on, from the other side.

        **This does not replace "a retry is the absence of a delete".** If the consumer
        dies before reaching either verb, the message still returns when its processing
        window lapses, and it returns *promptly* rather than after a long backoff - which
        is right, because a crashed consumer and a failed write are different events. One
        should be retried at once; the other should be given room.
        """
        message_id = self._inflight.get(receipt_handle)
        if message_id is None:
            raise ReceiptHandleIsInvalid(f"unknown or expired handle: {receipt_handle[:12]}...")
        entry = self._entries[message_id]
        entry.deadline = self._clock() + self._backoff_for(entry.receive_count)

    def _backoff_for(self, receive_count: int) -> float:
        """30, 60, 120, 240, 480 - doubling from the visibility timeout, and capped.

        Anchored to the visibility timeout rather than to a constant of its own: the first
        retry should not come back sooner than a consumer is allowed to take.
        """
        return min(
            self._visibility_timeout * 2 ** (receive_count - 1),
            BACKOFF_CAP_SECONDS,
        )

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
            # The bound, next to the depth. A depth without a ceiling is a number nobody
            # can act on: 400 waiting means nothing until you know whether the limit is
            # 500 or 50,000. It is also the only way backpressure is visible before it
            # fires - a reader can watch the queue approach the point where the API starts
            # answering 429 instead of discovering it there.
            "capacity": self._maxsize,
        }

    def clear(self) -> None:
        """Drop every message, in any state.

        Demo affordance only. It is not part of the `EventQueue` port on purpose: no
        production caller should be able to discard in-flight work, so the capability
        does not exist at the interface the application depends on.
        """
        self._entries.clear()
        self._visible.clear()
        self._inflight.clear()
        self._dlq.clear()

    def dead_letters(self) -> list[Event]:
        """Messages that exhausted their retries. Reviewed by hand, never auto-replayed.

        Reachable only from inside this process, which is the point rather than an
        oversight: an in-process queue has no outside. The durable record is the ERROR
        line written when the message arrives here, carrying the whole event.
        """
        return list(self._dlq)

    def pending_events(self) -> list[Event]:
        """Everything the process would take with it if it stopped now.

        Visible and in-flight both count: an in-flight message was never acknowledged, so
        it is as lost as one still waiting. Used by the shutdown path to name what it is
        about to drop rather than only counting it.
        """
        return [entry.event for entry in self._entries.values()]

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
                # Say it out loud. This is the moment the system permanently gives up on
                # an event, and it used to be the only lifecycle transition that produced
                # no output: an operator tailing WARN saw five identical retry warnings
                # and then silence, which looks exactly like recovery.
                if len(self._dlq) == DLQ_MAXLEN:
                    # The one being *discarded*, which is the only one about to become
                    # unrecoverable. Naming the arrival instead told the operator about the
                    # event that was fine and said nothing about the one being lost.
                    log.error(
                        "dead-letter queue is full at %d; discarding %s to admit %s",
                        DLQ_MAXLEN,
                        self._dlq[0].event_id,
                        entry.event.event_id,
                    )
                # The whole event, not a summary. The dead-letter lives in this process's
                # memory, so nothing outside can read it and a restart takes it with them:
                # "reviewed by hand" has a deadline nobody set. Writing the payload here
                # makes the log the durable record, which is the only recovery path an
                # in-process queue can honestly offer. A real SQS DLQ is a queue you can
                # consume from, and that is one of the things §4 says it buys.
                log.error(
                    "dead-lettering %s after %d deliveries: %s",
                    entry.event.event_id,
                    entry.receive_count,
                    entry.event.model_dump_json(),
                )
                self._dlq.append(entry.event)
                del self._entries[message_id]
            else:
                self._visible.append(message_id)
