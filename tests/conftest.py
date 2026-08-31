"""Shared fixtures.

The environment is configured **before importing anything from `app`**: settings are a
module-level singleton built at import time, so anything set afterwards would be ignored.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable

# --- must run before any `app.*` import -----------------------------------------------
os.environ.setdefault("MONGO_DB", "feathr_test")
os.environ.setdefault("ELASTICSEARCH_INDEX", "events_test")
# Redis database 1, not 0. Isolating MongoDB and Elasticsearch is not enough: the cache
# key is derived from the query parameters, so any other client asking for the same
# aggregation - the console polls exactly this one every two seconds - shares the entry
# and can overwrite it between a test's two reads. That produced a genuinely flaky
# failure, and only while the dashboard happened to be open.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
# A 30s visibility timeout would make the retry test take 30 seconds. One second is
# enough to observe the same behaviour.
os.environ.setdefault("VISIBILITY_TIMEOUT", "1.0")
os.environ.setdefault("WORKER_POLL_INTERVAL", "0.01")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# --------------------------------------------------------------------------------------

import httpx
import pytest

from app.config import settings
from app.stores import COLLECTION

STACK_URLS = {
    "mongodb": settings.mongo_uri,
    "elasticsearch": settings.elasticsearch_url,
    "redis": settings.redis_url,
}


async def eventually(
    predicate: Callable[[], object],
    *,
    timeout: float = 15.0,
    interval: float = 0.05,
    what: str = "condition",
) -> None:
    """Wait for a condition instead of sleeping a fixed amount.

    Integration tests cross process-internal boundaries (HTTP -> queue -> worker -> store)
    with no completion signal. A fixed sleep is either flaky or slow; polling is neither.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"{what} did not happen within {timeout}s")


def depth(queue) -> dict[str, int]:
    """The three counters, without the queue's configured bound.

    `stats()` also reports `capacity`, which is a setting rather than a measurement.
    Asserting the whole dict tied five tests to a constant none of them was about, and
    all five broke the day the bound became observable.
    """
    counters = queue.stats()
    return {k: counters[k] for k in ("visible", "in_flight", "dlq")}


@pytest.fixture(scope="session")
def stack_required() -> None:
    """Skip integration tests when the stack is not running, instead of failing.

    A missing stack is a setup problem, not a defect: reporting it as a failure would
    train people to ignore red tests.
    """
    try:
        response = httpx.get(f"{settings.elasticsearch_url}/", timeout=3.0)
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"the stack is not reachable ({exc}). Run `make up` first.")


@pytest.fixture
async def clean_stores(stack_required: None) -> AsyncIterator[None]:
    """Empty MongoDB and Elasticsearch around every test.

    Uses dedicated `feathr_test` / `events_test` targets, so a careless run can never
    delete development data.
    """
    from app import clients

    handles = await clients.connect()
    try:
        await handles.db[COLLECTION].drop()
        await handles.elasticsearch.options(ignore_status=404).indices.delete(
            index=settings.elasticsearch_index
        )
        await handles.redis.flushdb()
        yield
    finally:
        await clients.disconnect(handles)


@pytest.fixture
async def client(clean_stores: None) -> AsyncIterator[httpx.AsyncClient]:
    """The real application, wired by its own lifespan.

    The lifespan runs for real, so the test exercises the actual composition — queue,
    worker, stores and index — rather than a hand-assembled approximation.
    """
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            http.app = app  # type: ignore[attr-defined]
            yield http


async def refresh_index() -> None:
    """Force Elasticsearch to make recent writes searchable.

    `refresh_interval` defaults to **1 second**, so a document is indexed but not yet
    searchable the instant the worker returns. Production wants that buffer; a test that
    searches immediately without this call fails intermittently, which is the classic way
    Elasticsearch integration suites become untrustworthy.
    """
    from app import clients

    handles = await clients.connect()
    try:
        await handles.elasticsearch.indices.refresh(index=settings.elasticsearch_index)
    finally:
        await clients.disconnect(handles)
