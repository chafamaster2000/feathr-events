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
from app.worker import EventWorker


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
    assert queue.stats() == {"visible": 0, "in_flight": 0, "dlq": 0}


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
    assert queue.stats() == {"visible": 0, "in_flight": 0, "dlq": 0}


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
