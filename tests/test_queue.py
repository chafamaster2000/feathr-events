"""The queue's state machine.

Each test corresponds to a behaviour observed by running ElasticMQ (an SQS-compatible
server) — not to a reading of the documentation. See ARCHITECTURE.md §4.

The clock is injected: tests advance time instead of sleeping, so the suite runs in
milliseconds and has no races.
"""

from __future__ import annotations

import logging

import pytest

from app import queue as queue_module
from app.models import Event, EventIn
from app.queue import InMemoryEventQueue, QueueFull, ReceiptHandleIsInvalid
from tests.conftest import depth


class FakeClock:
    """A hand-driven monotonic clock."""

    def __init__(self) -> None:
        self._t = 1000.0

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def queue(clock: FakeClock) -> InMemoryEventQueue:
    return InMemoryEventQueue(visibility_timeout=30.0, max_receives=3, clock=clock)


def make_event(user: str = "u1") -> Event:
    return Event.from_input(
        EventIn(event_type="pageview", user_id=user, source_url="https://example.com/a")
    )


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


async def test_send_then_receive_returns_the_event(queue: InMemoryEventQueue) -> None:
    event = make_event()
    await queue.send(event)

    [message] = await queue.receive()

    assert message.event.event_id == event.event_id
    assert message.receive_count == 1
    assert message.receipt_handle


async def test_delete_is_the_ack_and_removes_it_permanently(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    await queue.send(make_event())
    [message] = await queue.receive()

    await queue.delete(message.receipt_handle)

    # Even once the visibility timeout lapses it does not return: the delete is final.
    clock.advance(120)
    assert await queue.receive() == []
    assert depth(queue) == {"visible": 0, "in_flight": 0, "dlq": 0}


# --------------------------------------------------------------------------
# The invisible state
# --------------------------------------------------------------------------


async def test_while_lent_out_no_one_else_can_see_it(queue: InMemoryEventQueue) -> None:
    await queue.send(make_event())
    await queue.receive()

    # Another worker asks for work at the same instant: nothing is available.
    assert await queue.receive() == []
    assert queue.stats()["in_flight"] == 1


async def test_when_the_timeout_lapses_it_returns_with_the_counter_incremented(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    await queue.send(make_event())
    [first] = await queue.receive()

    clock.advance(31)  # the worker died and never deleted

    [second] = await queue.receive()

    assert second.receive_count == 2
    assert second.event.event_id == first.event.event_id
    # Nobody re-enqueued it by hand: the retry is the absence of a delete.


async def test_the_old_handle_becomes_invalid_after_redelivery(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    """Closes the zombie-worker race.

    A stalls, the message is redelivered to B, B completes it, and then A revives and
    issues its delete. Without handle invalidation, A would delete someone else's work.
    """
    await queue.send(make_event())
    [a] = await queue.receive()

    clock.advance(31)
    [b] = await queue.receive()

    assert a.receipt_handle != b.receipt_handle
    with pytest.raises(ReceiptHandleIsInvalid):
        await queue.delete(a.receipt_handle)
    # And B's work still stands.
    await queue.delete(b.receipt_handle)


# --------------------------------------------------------------------------
# Backoff and the dead-letter queue
# --------------------------------------------------------------------------


async def test_a_reported_failure_lengthens_the_wait_before_the_next_attempt(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    """The backoff applies when a consumer reports it could not do the work.

    This test used to assert that `receive()` alone grew the invisibility, and it passed
    for as long as the system had no working backoff at all. That is the interesting part:
    the queue really did grow the deadline, and the worker really did heartbeat its
    processing window at the start of every delivery, and the heartbeat overwrote the
    growth. Each half was correct and tested; the composition was neither. The gaps
    between real attempts were flat 30s while this file certified they doubled.

    So the two are separate now, and each is asserted where it actually lives:
    `receive()` grants a processing window, `fail()` sets the retry delay, and
    `test_worker.py` asserts what the two produce together.
    """
    await queue.send(make_event())

    message = (await queue.receive())[0]  # attempt 1 -> a 30s window to work in
    await queue.fail(message.receipt_handle)  # tried, could not -> back off 30s

    clock.advance(31)
    message = (await queue.receive())[0]  # attempt 2
    await queue.fail(message.receipt_handle)  # -> back off 60s

    clock.advance(31)  # enough for the first backoff, not for the second
    assert await queue.receive() == []

    clock.advance(31)  # now it is
    assert len(await queue.receive()) == 1


async def test_the_window_a_consumer_gets_is_not_the_wait_after_it_fails(
    clock: FakeClock,
) -> None:
    """The conflation ARCHITECTURE 4 named as a weakness, now absent.

    "A message on its fifth attempt that fails in five seconds still sits invisible for
    the remaining 475." It does not: the window a consumer is granted and the delay it
    earns by failing are different numbers, decided at different moments.
    """
    queue = InMemoryEventQueue(visibility_timeout=30.0, max_receives=9, clock=clock)
    await queue.send(make_event())

    for _ in range(3):  # get the delivery count up, so the backoff is well past 30s
        message = (await queue.receive())[0]
        await queue.fail(message.receipt_handle)
        clock.advance(500)

    # A fourth delivery. Its window is still 30s, however long its backoff has grown.
    await queue.receive()
    clock.advance(31)
    assert len(await queue.receive()) == 1, "the granted window grew with the backoff"


async def test_failing_with_a_stale_handle_is_refused(queue: InMemoryEventQueue) -> None:
    """Same rule as `delete`: the handle belongs to the delivery, not to the message.

    Without it a consumer reviving after its window lapsed would push back the deadline
    of a delivery that now belongs to somebody else.
    """
    await queue.send(make_event())
    first = (await queue.receive())[0]
    await queue.change_visibility(first.receipt_handle, 0.0)
    await queue.receive()  # redelivered: `first`'s handle is now stale

    with pytest.raises(ReceiptHandleIsInvalid):
        await queue.fail(first.receipt_handle)


async def test_exhausting_the_attempts_routes_it_to_the_dead_letter_queue(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    event = make_event()
    await queue.send(event)

    for _ in range(3):  # max_receives=3
        assert await queue.receive()
        clock.advance(10_000)  # lapse any backoff

    assert await queue.receive() == []
    assert depth(queue) == {"visible": 0, "in_flight": 0, "dlq": 1}
    assert queue.dead_letters()[0].event_id == event.event_id


async def test_the_dead_letter_queue_is_bounded_and_says_so(
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dead-lettering frees the entry it came from, so nothing else stops it.

    A sustained downstream outage pushes every accepted event through this path. While
    the dead-letter was an unbounded list it counted against no limit and never stopped
    growing, in a queue whose own design argues that an unbounded queue protects nothing.
    """
    # Patched, not assigned: a bare module mutation would leave every later test in the
    # session running against a dead-letter of two.
    monkeypatch.setattr(queue_module, "DLQ_MAXLEN", 2)
    small = InMemoryEventQueue(visibility_timeout=30.0, max_receives=1, clock=clock)

    caplog.set_level(logging.ERROR, logger="app.queue")
    for _ in range(4):
        await small.send(make_event())
        assert await small.receive()
        clock.advance(10_000)
    assert await small.receive() == []

    assert small.stats()["dlq"] == 2, "the dead-letter grew past its bound"
    # The transition an operator has to be able to see. Without it, five retry warnings
    # followed by silence is indistinguishable from recovery.
    assert sum("dead-lettering" in r.message for r in caplog.records) == 4
    assert any("dead-letter queue is full" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# Heartbeat and backpressure
# --------------------------------------------------------------------------


async def test_change_visibility_extends_the_loan(
    queue: InMemoryEventQueue, clock: FakeClock
) -> None:
    """For long jobs: "still alive, give me more time"."""
    await queue.send(make_event())
    [message] = await queue.receive()

    await queue.change_visibility(message.receipt_handle, 300)

    clock.advance(31)  # the original timeout would have lapsed
    assert await queue.receive() == []


async def test_a_bounded_queue_refuses_instead_of_dying(clock: FakeClock) -> None:
    """Backpressure.

    An unbounded queue protects nothing: it grows until the process runs out of memory
    and takes everything queued with it. Rejecting is honest; accepting and dying later
    is not. The API translates this to a 429.
    """
    small = InMemoryEventQueue(maxsize=2, clock=clock)
    await small.send(make_event())
    await small.send(make_event())

    with pytest.raises(QueueFull):
        await small.send(make_event())


async def test_receive_respects_max_n(queue: InMemoryEventQueue) -> None:
    for _ in range(5):
        await queue.send(make_event())

    messages = await queue.receive(max_n=3)

    assert len(messages) == 3
    # Distinct handles: every delivery is an independent loan.
    assert len({m.receipt_handle for m in messages}) == 3
    assert depth(queue) == {"visible": 2, "in_flight": 3, "dlq": 0}
