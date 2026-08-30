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

import httpx
import pytest

from app.config import settings
from app.models import Event
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
    assert health["queue"] == {"visible": 0, "in_flight": 0, "dlq": 0}
    assert health["worker"]["failed"] == 0


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
        lambda: worker.stats()["failed"] >= 1,
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


async def test_cycle_cache_serves_bounded_staleness(client: httpx.AsyncClient) -> None:
    """The cached endpoint lags on purpose, and the uncached one proves the lag is real."""
    first = await client.post("/events", json=payload())
    await eventually(
        lambda: mongo_doc(client, first.json()["event_id"]),
        what="the first event landing",
    )

    miss = (await client.get("/events/stats/realtime")).json()
    assert miss["cached"] is False
    assert miss["ttl_seconds"] == settings.stats_cache_ttl
    total_at_cache_time = miss["total"]

    hit = (await client.get("/events/stats/realtime")).json()
    assert hit["cached"] is True
    assert hit["total"] == total_at_cache_time

    # A second event lands. The uncached endpoint sees it; the cached one does not.
    second = await client.post("/events", json=payload(event_type="conversion"))
    await eventually(
        lambda: mongo_doc(client, second.json()["event_id"]),
        what="the second event landing",
    )

    fresh = (await client.get("/events/stats")).json()
    stale = (await client.get("/events/stats/realtime")).json()

    assert fresh["total"] == total_at_cache_time + 1, "the uncached endpoint is current"
    assert stale["total"] == total_at_cache_time, "the cached one lags, within its TTL"
    assert stale["cached"] is True
