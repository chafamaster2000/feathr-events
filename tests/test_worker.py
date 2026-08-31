"""The worker: what it does, and above all what it does NOT do when something fails.

Everything with doubles: the failure and retry logic is verified without starting a
single database. That is the reason `EventStore` and `EventIndex` are Protocols rather
than concrete classes.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.models import Event, EventIn
from app.queue import InMemoryEventQueue
from app.worker import SINK_FAILURE_THRESHOLD, EventWorker, SinkCircuit
from tests.conftest import depth


class FakeClock:
    def __init__(self) -> None:
        self._t = 1000.0

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class FakeStore:
    """A double for MongoDB."""

    def __init__(self, *, failing: bool = False) -> None:
        self.saved: dict[str, Event] = {}
        self.writes = 0
        self.failing = failing

    async def upsert(self, event: Event) -> None:
        if self.failing:
            raise RuntimeError("mongodb is not responding")
        self.writes += 1
        self.saved[event.event_id] = event

    async def ensure_schema(self) -> None:  # pragma: no cover
        pass


class FakeIndex:
    """A double for Elasticsearch."""

    def __init__(self, *, failing: bool = False) -> None:
        self.indexed: dict[str, Event] = {}
        self.failing = failing

    async def index(self, event: Event) -> None:
        if self.failing:
            raise RuntimeError("elasticsearch is not responding")
        self.indexed[event.event_id] = event

    async def ensure_schema(self) -> None:  # pragma: no cover
        pass


async def eventually(predicate, timeout: float = 3.0, interval: float = 0.01) -> None:
    """Wait for a condition instead of sleeping a fixed amount."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("the condition did not hold within the timeout")


def make_event(user: str = "u1") -> Event:
    return Event.from_input(
        EventIn(event_type="pageview", user_id=user, source_url="https://example.com/a")
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def queue(clock: FakeClock) -> InMemoryEventQueue:
    return InMemoryEventQueue(visibility_timeout=30.0, max_receives=3, clock=clock)


def make_worker(queue, store, index, concurrency: int = 1) -> EventWorker:
    return EventWorker(queue, store, index, concurrency=concurrency, poll_interval=0.01)


# --------------------------------------------------------------------------


async def test_happy_path_writes_to_both_and_deletes_the_message(queue) -> None:
    store, index = FakeStore(), FakeIndex()
    event = make_event()
    await queue.send(event)

    worker = make_worker(queue, store, index)
    await worker.start()
    await eventually(lambda: worker.stats()["processed"] == 1)
    await worker.stop()

    assert store.saved[event.event_id].event_id == event.event_id
    assert index.indexed[event.event_id].event_id == event.event_id
    # Genuinely deleted: neither visible nor in flight.
    assert depth(queue) == {"visible": 0, "in_flight": 0, "dlq": 0}


async def test_when_mongodb_fails_the_message_is_not_deleted(queue) -> None:
    store, index = FakeStore(failing=True), FakeIndex()
    await queue.send(make_event())

    worker = make_worker(queue, store, index)
    await worker.start()
    await eventually(lambda: worker.stats()["failed_attempts"] >= 1)
    await worker.stop()

    assert index.indexed == {}  # Elasticsearch was never reached: MongoDB goes first
    assert queue.stats()["in_flight"] == 1  # still lent out, it will come back


async def test_when_elasticsearch_fails_mongodb_still_has_it_and_the_message_returns(
    queue, clock
) -> None:
    """The core of the dual write.

    MongoDB was written and Elasticsearch was not: the system is divergent. The retry
    rewrites MongoDB pointlessly, and that is acceptable *only because* the upsert is
    idempotent.
    """
    store, index = FakeStore(), FakeIndex(failing=True)
    event = make_event()
    await queue.send(event)

    worker = make_worker(queue, store, index)
    await worker.start()
    await eventually(lambda: worker.stats()["failed_attempts"] >= 1)

    assert event.event_id in store.saved  # the source of truth has it
    assert index.indexed == {}  # the derived index does not
    assert queue.stats()["in_flight"] == 1

    # It recovers on its own once Elasticsearch returns: nobody re-enqueued anything.
    index.failing = False
    clock.advance(31)
    await eventually(lambda: worker.stats()["processed"] == 1)
    await worker.stop()

    assert event.event_id in index.indexed
    assert store.writes == 2  # rewritten: idempotent, not duplicated
    assert len(store.saved) == 1


async def test_an_always_failing_event_ends_up_in_the_dead_letter_queue(queue, clock) -> None:
    store, index = FakeStore(), FakeIndex(failing=True)
    event = make_event()
    await queue.send(event)

    worker = make_worker(queue, store, index)
    await worker.start()
    for _ in range(3):  # max_receives=3
        await eventually(lambda: queue.stats()["in_flight"] == 1)
        clock.advance(10_000)
        await asyncio.sleep(0.05)
    await eventually(lambda: queue.stats()["dlq"] == 1)
    await worker.stop()

    assert queue.dead_letters()[0].event_id == event.event_id
    assert queue.stats()["visible"] == 0  # it is not still circulating


async def test_several_consumers_share_the_work_without_colliding(queue) -> None:
    store, index = FakeStore(), FakeIndex()
    ids = set()
    for i in range(50):
        event = make_event(user=f"u{i}")
        ids.add(event.event_id)
        await queue.send(event)

    worker = make_worker(queue, store, index, concurrency=8)
    await worker.start()
    await eventually(lambda: worker.stats()["processed"] == 50)
    await worker.stop()

    assert set(store.saved) == ids
    assert store.writes == 50  # exactly one write per event: nobody stepped on anybody
    assert depth(queue) == {"visible": 0, "in_flight": 0, "dlq": 0}


async def test_stop_drains_what_was_in_flight(queue) -> None:
    store, index = FakeStore(), FakeIndex()
    for _ in range(20):
        await queue.send(make_event())

    worker = make_worker(queue, store, index, concurrency=4)
    await worker.start()
    await eventually(lambda: worker.stats()["processed"] == 20)
    await worker.stop()

    assert worker.stats()["consumers"] == 0  # no task was left hanging
    assert queue.stats()["in_flight"] == 0


async def test_it_cannot_be_started_twice(queue) -> None:
    worker = make_worker(queue, FakeStore(), FakeIndex())
    await worker.start()
    with pytest.raises(RuntimeError):
        await worker.start()
    await worker.stop()


# --- the sink circuit ------------------------------------------------------------------
#
# The defect it fixes: with `max_receives=5` the last delivery falls at 930 seconds, so a
# sink down for about fifteen minutes dead-letters every event in flight as poison, when
# nothing was wrong with any of them. The queue cannot tell the difference - from where it
# sits there is none. The consumer can.


def circuit(clock: FakeClock, **kwargs) -> SinkCircuit:
    return SinkCircuit(clock=clock, pause=5.0, **kwargs)


def test_one_failing_event_does_not_open_the_circuit(clock: FakeClock) -> None:
    """A poison message must still dead-letter, and this is the line between the two.

    One event failing over and over is a message problem. Pausing the whole worker for it
    would let one bad payload stop the pipeline - the exact opposite of what a dead-letter
    queue is for.
    """
    c = circuit(clock)
    for _ in range(20):
        c.record_failure("the-same-event")

    assert c.is_open is False
    assert c.allowance(10) == 10


def test_distinct_events_failing_in_a_row_open_it(clock: FakeClock) -> None:
    c = circuit(clock)
    for i in range(SINK_FAILURE_THRESHOLD):
        c.record_failure(f"event-{i}")

    assert c.is_open is True
    assert c.allowance(10) == 0


def test_a_success_anywhere_clears_the_evidence(clock: FakeClock) -> None:
    """The run has to be unbroken. Two failures an hour apart are not an outage."""
    c = circuit(clock)
    c.record_failure("a")
    c.record_failure("b")
    c.record_success()
    c.record_failure("c")

    assert c.is_open is False


def test_the_probe_is_one_message_and_only_one_consumer_holds_it(clock: FakeClock) -> None:
    """Eight consumers probing with ten messages each would burn eighty deliveries to
    answer a question one message answers."""
    c = circuit(clock)
    for i in range(SINK_FAILURE_THRESHOLD):
        c.record_failure(f"event-{i}")
    clock.advance(5.0)

    assert c.allowance(10) == 1  # the first consumer to ask
    assert c.allowance(10) == 0  # every other one waits
    assert c.allowance(10) == 0


def test_an_abandoned_probe_is_returned_not_held(clock: FakeClock) -> None:
    """An empty queue answers nothing about the sinks. Held, the probe is held forever and
    consumption never resumes - the failure mode would be a worker that never comes back
    from an outage that ended."""
    c = circuit(clock)
    for i in range(SINK_FAILURE_THRESHOLD):
        c.record_failure(f"event-{i}")
    clock.advance(5.0)
    c.allowance(10)
    c.abandon_probe()

    assert c.allowance(10) == 1


def test_the_pause_doubles_and_is_capped(clock: FakeClock) -> None:
    c = circuit(clock, max_pause=20.0)
    delays = []
    for cycle in range(5):
        c.record_failure(f"event-{cycle}-a")
        c.record_failure(f"event-{cycle}-b")
        c.record_failure(f"event-{cycle}-c")
        delays.append(round(c.seconds_remaining()))
        clock.advance(c.seconds_remaining())

    assert delays == [5, 10, 20, 20, 20]


def test_a_pile_of_simultaneous_failures_escalates_once(clock: FakeClock) -> None:
    """Eight consumers fail together at the onset of an outage. Without this the backoff
    would escalate eight times in one instant and jump straight to the cap."""
    c = circuit(clock)
    for i in range(8):
        c.record_failure(f"event-{i}")

    assert c.seconds_remaining() == 5.0


async def test_an_outage_no_longer_dead_letters_the_backlog(clock: FakeClock) -> None:
    """The whole point, end to end.

    Ten events, a store that is down, and enough elapsed time that the old design would
    have delivered each of them `max_receives` times and dead-lettered all ten. Because
    the worker stops pulling, the backlog waits in the queue instead of spending delivery
    attempts on a dependency that is not there - and when the store comes back, every one
    of them is written.

    Confirmed to fail without the circuit: raising the threshold out of reach dead-letters
    all ten. A regression test nobody has watched fail is a test of nothing.
    """
    queue = InMemoryEventQueue(visibility_timeout=30.0, max_receives=3, clock=clock)
    store, index = FakeStore(failing=True), FakeIndex()
    events = [make_event(f"u{i}") for i in range(10)]
    for event in events:
        await queue.send(event)

    worker = EventWorker(
        queue, store, index, concurrency=1, poll_interval=0.01, circuit=circuit(clock)
    )
    await worker.start()
    try:
        await eventually(lambda: worker.stats()["paused"] is True)

        # Six windows of 400 fake seconds. `max_receives=3` here puts the giving-up point
        # at 210s, so 2,400s is more than ten times the budget the old design had.
        for _ in range(6):
            clock.advance(400.0)
            await asyncio.sleep(0.05)

        assert depth(queue)["dlq"] == 0, "the backlog was dead-lettered during an outage"

        store.failing = False
        clock.advance(400.0)
        await eventually(lambda: len(store.saved) == 10, timeout=5.0)
    finally:
        await worker.stop()

    assert depth(queue) == {"visible": 0, "in_flight": 0, "dlq": 0}


async def test_the_pause_is_reported_so_a_stalled_worker_is_not_read_as_an_idle_one(
    clock: FakeClock,
) -> None:
    """Both report zero throughput and only one of them is a problem.

    Without this the console shows a queue filling beside a worker that looks healthy,
    and nothing says the worker stopped pulling on purpose.
    """
    queue = InMemoryEventQueue(visibility_timeout=30.0, max_receives=3, clock=clock)
    store, index = FakeStore(failing=True), FakeIndex()
    for i in range(5):
        await queue.send(make_event(f"u{i}"))

    worker = EventWorker(
        queue, store, index, concurrency=1, poll_interval=0.01, circuit=circuit(clock)
    )
    assert worker.stats()["paused"] is False

    await worker.start()
    try:
        await eventually(lambda: worker.stats()["paused"] is True)
        assert worker.stats()["resumes_in"] > 0
    finally:
        await worker.stop()
