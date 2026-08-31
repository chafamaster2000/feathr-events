"""Full request lifecycles against the real stack.

The brief asks for "integration tests covering at least two full request lifecycles".
There are four here, and they are not four variations of the same path — each one
exercises a different part of the system, and a different evaluation criterion:

    1. ingest -> worker -> MongoDB query     the literal example in the brief
    2. ingest -> worker -> Elasticsearch     the search path; MongoDB is not involved
    3. ingest -> failure -> retry -> both    the dual write, and how it recovers
    4. aggregation -> Redis -> bounded lag   the cache, and what it costs

Nothing is mocked. Real MongoDB, real Elasticsearch, real Redis, the application's own
lifespan. The only injected fault is in cycle 3, at the `EventIndex` seam — which is why
that seam is a Protocol.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest

from app.config import settings
from app.models import Event
from app.queries import LIVE_BIN_SECONDS
from app.stores import COLLECTION
from tests.conftest import eventually, refresh_index

pytestmark = pytest.mark.integration


def payload(**overrides: object) -> dict:
    base = {
        "event_type": "pageview",
        "user_id": "u-integration",
        "source_url": "https://shop.example.com/product/42",
        "metadata": {"browser": "firefox", "device": "mobile", "campaign": "spring-sale"},
    }
    return base | overrides


async def mongo_doc(client: httpx.AsyncClient, event_id: str) -> dict | None:
    db = client.app.state.clients.db  # type: ignore[attr-defined]
    return await db[COLLECTION].find_one({"_id": event_id})


# ---------------------------------------------------------------------------
# Cycle 1 — ingest -> worker -> query
# ---------------------------------------------------------------------------


async def test_cycle_ingest_worker_query(client: httpx.AsyncClient) -> None:
    """The lifecycle the brief names: POST, the worker processes, the query returns it."""
    response = await client.post("/events", json=payload())

    # 202, not 201: when we answer, the event is in the queue, not in MongoDB.
    assert response.status_code == 202
    event_id = response.json()["event_id"]
    assert response.json()["status"] == "accepted"

    await eventually(
        lambda: mongo_doc(client, event_id),
        what="the worker writing the event to MongoDB",
    )

    listing = await client.get("/events", params={"event_type": "pageview"})
    assert listing.status_code == 200
    found = [item for item in listing.json()["items"] if item["event_id"] == event_id]
    assert len(found) == 1
    assert found[0]["user_id"] == "u-integration"
    assert found[0]["metadata"]["campaign"] == "spring-sale"

    # The queue is empty and nothing was dead-lettered: the message was acknowledged.
    health = (await client.get("/health")).json()
    assert {k: health["queue"][k] for k in ("visible", "in_flight", "dlq")} == {
        "visible": 0,
        "in_flight": 0,
        "dlq": 0,
    }
    # The bound travels with the depth, because one is meaningless without the other.
    assert health["queue"]["capacity"] == settings.queue_maxsize
    assert health["worker"]["failed_attempts"] == 0


# ---------------------------------------------------------------------------
# Cycle 2 — ingest -> worker -> full-text search
# ---------------------------------------------------------------------------


async def test_cycle_ingest_worker_search(client: httpx.AsyncClient) -> None:
    """The search path. MongoDB does not participate in answering this query."""
    response = await client.post("/events", json=payload(metadata={"browser": "webkit-nightly"}))
    event_id = response.json()["event_id"]

    await eventually(
        lambda: mongo_doc(client, event_id),
        what="the worker completing both writes",
    )
    # Without this the test is a coin flip: refresh_interval defaults to 1s, so the
    # document is indexed but not yet searchable. See conftest.refresh_index.
    await refresh_index()

    results = await client.get("/events/search", params={"q": "webkit-nightly"})
    assert results.status_code == 200
    body = results.json()
    assert body["total"] == 1
    assert body["items"][0]["event_id"] == event_id


# ---------------------------------------------------------------------------
# Cycle 3 — the dual write, and its recovery
# ---------------------------------------------------------------------------


class FlakyIndex:
    """Wraps the real index and fails the first N attempts.

    Injected at the `EventIndex` seam, which exists as a Protocol precisely so failure
    paths can be exercised without taking a container down.
    """

    def __init__(self, real: object, fail_times: int) -> None:
        self._real = real
        self._remaining = fail_times
        self.attempts = 0

    async def index(self, event: Event) -> None:
        self.attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("elasticsearch unavailable (injected)")
        await self._real.index(event)  # type: ignore[attr-defined]

    async def ensure_schema(self) -> None:  # pragma: no cover
        await self._real.ensure_schema()  # type: ignore[attr-defined]


async def test_cycle_dual_write_diverges_then_recovers(client: httpx.AsyncClient) -> None:
    """MongoDB succeeds, Elasticsearch fails, and the system converges on its own.

    This is the failure the brief never mentions. What it demonstrates:

    * the divergent state is real — the event exists but cannot be found;
    * nobody re-enqueues anything: the retry is the *absence* of a delete;
    * re-writing MongoDB is harmless only because the upsert is idempotent, so one
      document exists at the end, not two.
    """
    worker = client.app.state.worker  # type: ignore[attr-defined]
    flaky = FlakyIndex(worker._index, fail_times=1)
    worker._index = flaky  # reaching in is deliberate: the seam has no public setter

    response = await client.post("/events", json=payload(metadata={"marker": "dual-write"}))
    event_id = response.json()["event_id"]

    # The first attempt fails after MongoDB was already written: this is the divergence.
    await eventually(
        lambda: worker.stats()["failed_attempts"] >= 1,
        what="the first attempt failing on Elasticsearch",
    )
    assert await mongo_doc(client, event_id) is not None, "the source of truth has it"
    await refresh_index()
    missing = await client.get("/events/search", params={"q": "dual-write"})
    assert missing.json()["total"] == 0, "the derived index does not"

    # Nothing re-enqueued it. The visibility timeout lapses and it comes back on its own.
    await eventually(
        lambda: worker.stats()["processed"] >= 1,
        what="the retry succeeding once Elasticsearch recovers",
    )
    await refresh_index()

    recovered = await client.get("/events/search", params={"q": "dual-write"})
    assert recovered.json()["total"] == 1
    assert recovered.json()["items"][0]["event_id"] == event_id

    # MongoDB was written twice and holds exactly one document.
    assert flaky.attempts == 2
    db = client.app.state.clients.db  # type: ignore[attr-defined]
    assert await db[COLLECTION].count_documents({"_id": event_id}) == 1


# ---------------------------------------------------------------------------
# Cycle 4 — the cache, and the staleness it buys
# ---------------------------------------------------------------------------


async def test_cycle_cache_serves_a_closed_window(client: httpx.AsyncClient) -> None:
    """The cached live summary describes a window that has already ended.

    This used to assert that the cached total lagged the uncached one by exactly the
    events posted in between. That comparison no longer means anything, and the change is
    the point: `/events/stats` is every event at hourly granularity, while the live
    summary is closed two-second bins over the last five minutes. They answer different
    questions now, so equal totals would be the surprising outcome.

    What replaced it is the stronger property. Because the bin still filling is excluded,
    a cached answer is not an out-of-date view of the present — it is the exact answer for
    a window that closed. Two calls inside one slot must therefore be identical, not
    merely close.
    """
    first = await client.post("/events", json=payload())
    await eventually(
        lambda: mongo_doc(client, first.json()["event_id"]),
        what="the first event landing",
    )

    # Land at the start of a bin before measuring. The cache key *is* the bin slot, so a
    # pair of calls that straddles a two-second boundary sees the key roll between them
    # and the second one legitimately recomputes. The test's premise is "two calls inside
    # one slot"; until now it stated that premise without establishing it, and failed
    # roughly once in six runs for a reason that was never a defect in the system.
    now = time.time()
    await asyncio.sleep(LIVE_BIN_SECONDS - (now % LIVE_BIN_SECONDS) + 0.05)

    miss = (await client.get("/events/stats/realtime")).json()
    assert miss["ttl_seconds"] == settings.stats_cache_ttl

    hit = (await client.get("/events/stats/realtime")).json()
    assert hit["cached"] is True
    for field in ("since", "until", "total", "series"):
        assert hit[field] == miss[field], f"{field} moved inside one slot"

    # The window ends at a bin that has closed, never at the present moment.
    until = datetime.fromisoformat(miss["until"])
    assert until <= datetime.now(UTC).replace(tzinfo=None), "the filling bin was included"
    assert (until - datetime.fromisoformat(miss["since"])).total_seconds() == miss["window_seconds"]

    # Dense, and filled server-side: a client that had to infer the axis from the bins
    # that happen to hold events would render scattered moments as consecutive ones.
    slots = miss["window_seconds"] // miss["bin_seconds"]
    for entry in miss["series"]:
        assert len(entry["counts"]) == slots, "the series is not dense"
        assert sum(entry["counts"]) == entry["total"]


async def test_the_two_kinds_of_429_are_told_apart(client: httpx.AsyncClient) -> None:
    """Backpressure and throttling share a status code, so they must not share a story.

    `app/ratelimit.py` asserts its own half of this pair. Asserting only that half would
    leave the contract half-tested: a header the limiter sets and the ingest route
    forgets is worse than no header, because the console would then read every queue-full
    refusal as "you are asking too fast" and tell the operator to slow down while the
    real problem was the worker falling behind.
    """
    from app.queue import QueueFull

    class Full:
        async def send(self, event: object) -> None:
            raise QueueFull

    real = client.app.state.queue
    client.app.state.queue = Full()
    try:
        response = await client.post(
            "/events",
            json={
                "event_type": "click",
                "user_id": "u-1",
                "source_url": "https://shop.example.com/p/1",
                "metadata": {},
            },
        )
    finally:
        client.app.state.queue = real

    assert response.status_code == 429
    assert response.headers["x-throttle-reason"] == "queue_full"
    assert response.headers["retry-after"] == "1"
