"""API entry point.

The API writes to no database. It validates, enqueues and answers — the worker is the
only thing that touches MongoDB and Elasticsearch. That is why `POST /events` returns 202
and not 201: when we answer, the event is in the queue, not stored.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app import clients
from app.cache import StatsCache
from app.config import settings
from app.models import Event, EventAccepted, EventIn
from app.queries import Bucket, EventQueries
from app.queue import InMemoryEventQueue, QueueFull
from app.stores import ElasticEventIndex, MongoEventStore
from app.worker import EventWorker

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
)
log = logging.getLogger("feathr")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open connections, prepare the schemas, start the worker.

    The queue is a variable of this process: `app.state.queue`. It is not a service and
    not a container — it is an object in the memory of the same interpreter that runs the
    API, which is exactly what the brief means by "in-process".

    The corollary to keep in mind: raising `uvicorn --workers` BREAKS the model. Each
    process would have its own `app.state` and therefore its own queue, with none of them
    seeing the others. See ARCHITECTURE.md §5.
    """
    log.info("starting: connecting to mongo / elasticsearch / redis")
    app.state.clients = await clients.connect()

    store = MongoEventStore(app.state.clients.db)
    index = ElasticEventIndex(app.state.clients.elasticsearch, settings.elasticsearch_index)
    for name, component in (("mongodb", store), ("elasticsearch", index)):
        try:
            await component.ensure_schema()
        except Exception:
            # A failure creating indexes must not prevent startup: the app serves
            # degraded and the health check reflects it. Dying here would turn a
            # performance problem into an outage.
            log.warning("could not prepare the %s schema", name, exc_info=True)

    app.state.queue = InMemoryEventQueue(
        visibility_timeout=settings.visibility_timeout,
        max_receives=settings.max_receives,
        maxsize=settings.queue_maxsize,
    )
    app.state.worker = EventWorker(
        app.state.queue,
        store,
        index,
        concurrency=settings.worker_concurrency,
        batch_size=settings.worker_batch_size,
        poll_interval=settings.worker_poll_interval,
    )
    app.state.queries = EventQueries(
        app.state.clients.db, app.state.clients.elasticsearch, settings.elasticsearch_index
    )
    app.state.cache = StatsCache(app.state.clients.redis, ttl_seconds=settings.stats_cache_ttl)

    await app.state.worker.start()

    try:
        yield
    finally:
        log.info("shutting down: draining the worker and closing connections")
        await app.state.worker.stop()
        pending = app.state.queue.stats()
        if pending["visible"] or pending["in_flight"]:
            # This has to be said out loud: the queue lives in memory and goes with the
            # process. It is the honest cost of "in-process", and the reason SQS exists.
            log.warning("losing %s queued events on shutdown", pending)
        await clients.disconnect(app.state.clients)


app = FastAPI(
    title="Feathr Event Processing Platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post(
    "/events",
    response_model=EventAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ingestion"],
)
async def ingest(payload: EventIn, request: Request) -> EventAccepted:
    """Accept an event and enqueue it.

    The `event_id` is assigned HERE, before the queue. If it were born in the worker,
    every redelivery would generate a new id and the unique index would deduplicate
    nothing.
    """
    event: Event = Event.from_input(payload)
    try:
        await request.app.state.queue.send(event)
    except QueueFull:
        # Backpressure: rejecting is honest; accepting and dying later is not.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="the queue is full, retry later",
        ) from None
    return EventAccepted(event_id=event.event_id)


# ---------------------------------------------------------------------------
# Reads. Each one goes to the store that can answer it, and only one is cached.
# ---------------------------------------------------------------------------


@app.get("/events", tags=["query"])
async def list_events(
    request: Request,
    event_type: str | None = None,
    user_id: str | None = None,
    source_url: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Filter events in MongoDB.

    Not cached, on purpose: arbitrary filters produce a near-unique key per request, and
    caching what never repeats is pure cost. See ARCHITECTURE.md §3.
    """
    return await request.app.state.queries.list_events(
        event_type=event_type,
        user_id=user_id,
        source_url=source_url,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@app.get("/events/stats", tags=["query"])
async def stats(
    request: Request,
    bucket: Bucket = Bucket.DAILY,
    since: datetime | None = None,
    until: datetime | None = None,
    event_type: str | None = None,
) -> dict:
    """MongoDB aggregation: counts by type and time window.

    Also uncached. It is the same aggregation as `/stats/realtime` but with a different
    promise: here the caller expects the correct number. Serving it from cache would
    change the contract silently.
    """
    return await request.app.state.queries.stats(
        bucket=bucket, since=since, until=until, event_type=event_type
    )


@app.get("/events/search", tags=["query"])
async def search(
    request: Request,
    q: str = Query(min_length=1, description="text to match in metadata and the URL"),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Full-text in Elasticsearch. MongoDB does not participate in this path."""
    return await request.app.state.queries.search(q=q, limit=limit)


@app.get("/events/stats/realtime", tags=["query"])
async def stats_realtime(
    request: Request,
    bucket: Bucket = Bucket.HOURLY,
    event_type: str | None = None,
) -> dict:
    """The only endpoint that goes through the cache.

    Its name already admits what it returns: a summary, not the truth. That is why it can
    be served from Redis with a TTL without breaking any promise.

    Returns `cached` so the cache is observable from outside.
    """
    state = request.app.state
    key = state.cache.key(bucket=bucket.value, event_type=event_type)

    if (hit := await state.cache.get(key)) is not None:
        return {**hit, "cached": True, "ttl_seconds": state.cache.ttl}

    data = await state.queries.stats(bucket=bucket, event_type=event_type)
    await state.cache.set(key, data)
    return {**data, "cached": False, "ttl_seconds": state.cache.ttl}


@app.get("/health", tags=["ops"])
async def health(request: Request) -> JSONResponse:
    """The three dependencies, plus queue depth.

    Depth is the most informative number in the system: stable near zero means the worker
    outpaces ingestion; growing means the worker is the bottleneck.
    """
    state = request.app.state
    deps = await clients.health(state.clients)
    ok = all(v == "up" for v in deps.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "dependencies": deps,
            "queue": state.queue.stats(),
            "worker": state.worker.stats(),
        },
    )
