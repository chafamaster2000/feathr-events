"""API entry point.

The API writes to no database. It validates, enqueues and answers — the worker is the
only thing that touches MongoDB and Elasticsearch. That is why `POST /events` returns 202
and not 201: when we answer, the event is in the queue, not stored.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app import clients, faults
from app.cache import StatsCache
from app.config import settings
from app.models import Event, EventAccepted, EventIn
from app.observability import AgentLoggerMiddleware
from app.observability import log as agent_log
from app.queries import LIVE_BIN_SECONDS, Bucket, EventQueries
from app.queue import InMemoryEventQueue, QueueFull
from app.stores import COLLECTION, ElasticEventIndex, MongoEventStore
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
            #
            # The ids, not only the count. Every one of these was answered with a 202, and
            # the producer will never retry it — "losing 12 events" is not something anyone
            # can act on, while a list of ids is. The events are right here at the moment
            # they are lost, and printing them is the difference between an admitted
            # weakness and an auditable one.
            log.warning("losing %s queued events on shutdown", pending)
            for event in app.state.queue.pending_events():
                log.warning("lost on shutdown: %s", event.model_dump_json())
        await clients.disconnect(app.state.clients)


class FaultTarget(StrEnum):
    """A closed set: the caller names one of ours, never an arbitrary string.

    `worker` is not a dependency, and it is here because the brief names it. "What happens
    if the worker crashes mid-batch?" is one of the two failure modes the assignment asks
    about by name, and breaking a store cannot show it.
    """

    MONGODB = "mongodb"
    ELASTICSEARCH = "elasticsearch"
    REDIS = "redis"
    WORKER = "worker"


app = FastAPI(
    title="Feathr Event Processing Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Structured NDJSON per request into .logs/agent/, correlated by `x-agent-task-id`.
# Pure ASGI, so it does not interfere with streaming responses.
app.add_middleware(AgentLoggerMiddleware)


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
    # The domain's own correlation id, recorded next to the transport-level one: this is
    # the id that survives every hop (queue -> worker -> MongoDB -> Elasticsearch).
    agent_log("ingest.accepted", "event queued", ctx={"eventId": event.event_id})
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


@app.get("/events/search/terms", tags=["query"])
async def search_terms(
    request: Request,
    q: str | None = Query(None, max_length=64, description="only values beginning with this"),
    limit: int = Query(12, ge=1, le=50),
) -> dict:
    """The most common metadata values, so a search box has something to suggest.

    Derived from the data with a terms aggregation rather than hard-coded, which is what
    makes it stay honest as the data changes. With `q` the same aggregation answers a
    type-ahead: the values that begin with what has been typed, with their real counts.
    """
    return await request.app.state.queries.search_terms(limit=limit, starts_with=q)


@app.get("/events/stats/realtime", tags=["query"])
async def stats_realtime(
    request: Request,
    event_type: str | None = None,
) -> dict:
    """A lightweight summary of recent activity, served from Redis with a configurable TTL.

    Recent at a resolution you can watch: totals per type over the last ten minutes, plus
    one dense array of counts per ten-second bin. It used to answer with the same hourly
    aggregation as `/events/stats`, and at that granularity the current hour is a single
    bar that grows for sixty minutes — nothing it returned could change visibly while you
    watched it, whatever the route was called.

    Lightweight is part of the contract, so the shape is a summary rather than a grid:
    sixty bins across five types would be three hundred rows and roughly 22KB on an
    endpoint a live view polls every couple of seconds.

    Cached because polling constantly is exactly what a cache is for, and because this is
    the one read whose contract promises a summary rather than an exact figure. `cached`
    and `ttl_seconds` come back with it, so the staleness is observable from outside.
    """
    state = request.app.state
    # The window is truncated to the bin, so the key holds for a bin instead of moving
    # with every request and turning the cache into a write-only store.
    bin_now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    slot = bin_now - timedelta(seconds=bin_now.second % LIVE_BIN_SECONDS)
    key = state.cache.key(view="live", event_type=event_type, slot=slot)

    if (hit := await state.cache.get(key)) is not None:
        return {**hit, "cached": True, "ttl_seconds": state.cache.ttl}

    data = await state.queries.live_summary(event_type=event_type)
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


# ---------------------------------------------------------------------------
# Demo affordance. Registered ONLY when DEMO_MODE is on, so in a normal deployment
# this route does not exist at all - not disabled, absent. A destructive endpoint that
# merely checks a flag is one configuration mistake away from being live.
# ---------------------------------------------------------------------------

if settings.demo_mode:

    @app.get("/demo/fault", tags=["demo"])
    async def demo_faults_active(request: Request) -> dict:
        """Which dependencies are currently being simulated as down.

        The read half of the control, and it closes a real hazard rather than adding a
        convenience: without it a client that reloads cannot tell a left-over simulation
        from a genuine outage, and somebody spends an afternoon debugging a ghost. It
        exposes one list drawn from a closed set of three names, under the same
        `DEMO_MODE` gate as the write half.
        """
        stopped = ["worker"] if request.app.state.worker.stats()["consumers"] == 0 else []
        return {"faulted": [*faults.active(), *stopped]}

    @app.post("/demo/fault", tags=["demo"])
    async def demo_fault(request: Request, dependency: FaultTarget, down: bool = True) -> dict:
        """Simulate a dependency being unavailable, so §6's failure modes can be watched.

        Those claims are the least verifiable part of the design: nothing in the system
        will break itself, and what makes them interesting is what keeps working while
        something is broken. This flips one flag; the adapters then raise where a driver
        error would raise, so the code that handles it is the code that handles the real
        thing.

        Not a harness endpoint. It reads nothing, exposes no internals, and takes no target
        from the caller beyond a name from a closed set. Like `/demo/reset`, it is
        *registered* only under `DEMO_MODE` rather than disabled behind a check.

        It does not simulate a partition, a timeout, a slow dependency or a partial
        failure: it is the shape of "the dependency refused", not "the dependency went
        quiet". The console says the same thing where a reader will see it.
        """
        state = request.app.state
        if dependency is FaultTarget.WORKER:
            # Abruptly, not gracefully. `stop()` drains by default, which demonstrates a
            # clean shutdown - the opposite of the question. A zero drain window cancels
            # the tasks where they stand, so whatever was mid-message stays in flight with
            # its visibility deadline running. That is what "crashed mid-batch" means.
            if down:
                await state.worker.stop(drain_timeout=0.0)
            else:
                await state.worker.start()
        else:
            faults.enable(dependency.value) if down else faults.disable(dependency.value)
        log.warning("demo: %s is now simulated as %s", dependency.value, "down" if down else "up")
        stopped = ["worker"] if state.worker.stats()["consumers"] == 0 else []
        return {"faulted": [*faults.active(), *stopped]}

    @app.post("/demo/reset", tags=["demo"])
    async def demo_reset(request: Request) -> dict:
        """Empty every store so a demonstration can start from a known state.

        Scoped to this system's own data: it drops one collection and one index by name,
        and never takes a target from the caller.
        """
        state = request.app.state
        before = {
            "mongo": await state.clients.db[COLLECTION].count_documents({}),
            "queue": state.queue.stats(),
            "worker": state.worker.stats(),
        }
        state.queue.clear()
        # Otherwise the console shows empty stores next to a worker claiming it processed
        # thousands of events - two true statements that together read as a bug.
        state.worker.reset_counters()
        await state.clients.db[COLLECTION].drop()
        await state.clients.elasticsearch.options(ignore_status=404).indices.delete(
            index=settings.elasticsearch_index
        )
        await state.clients.redis.flushdb()

        index = ElasticEventIndex(state.clients.elasticsearch, settings.elasticsearch_index)
        store = MongoEventStore(state.clients.db)
        await index.ensure_schema()
        await store.ensure_schema()

        agent_log("demo.reset", "all stores emptied", ctx=before)
        return {"status": "reset", "cleared": before}
