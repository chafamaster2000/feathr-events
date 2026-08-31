"""Caching layer: Redis in front of exactly one read.

The cache does not wrap everything. It sits in front of the only endpoint whose contract
already admits it returns a snapshot rather than the truth: `/events/stats/realtime`.

**No invalidation, TTL only.** Not a shortcut — a decision with an argument. Precise
invalidation would require knowing which cached entries each incoming event affects, i.e.
evaluating every key against every write. In a pipeline built for high write volume, that
costs more than the aggregation being avoided.

And the TTL does not introduce the staleness: **it already exists upstream**. Ingestion is
asynchronous, so an accepted event is not in MongoDB yet. The TTL adds no new
inconsistency; it puts a known ceiling on the inconsistency that was already there.

See ARCHITECTURE.md §3.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any

from redis.asyncio import Redis

from app.faults import guard

log = logging.getLogger(__name__)

PREFIX = "feathr:stats"


def _encode(value: Any) -> str:
    """Serialise the way the uncached path does.

    `default=str` renders a datetime as "2026-08-25 00:00:00" while FastAPI emits
    "2026-08-25T00:00:00", so the same endpoint answered with two different timestamp
    formats depending on whether the response came from the cache. A client parsing
    those would work until the first cache hit. A cache must not change the shape of
    what it caches.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


class StatsCache:
    def __init__(self, redis: Redis, ttl_seconds: int = 30) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @property
    def ttl(self) -> int:
        return self._ttl

    def key(self, **params: Any) -> str:
        """Derive a key from normalised parameters.

        Keys are sorted so that `?bucket=daily&type=click` and `?type=click&bucket=daily`
        share an entry: they are the same question.
        """
        canonical = json.dumps(
            {k: v for k, v in sorted(params.items()) if v is not None}, default=_encode
        )
        return f"{PREFIX}:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"

    async def get(self, key: str) -> dict[str, Any] | None:
        """A Redis failure must NEVER break a read.

        The cache is an optimisation, not a dependency: if it fails, the cost is
        recomputing. Propagating the error would turn a performance degradation into an
        outage.

        The decode belongs inside the guard, not after it. A Redis *value* can be as
        broken as a Redis *connection* - truncated, written by an older schema, or left
        at the same key by another process - and `json.loads` outside the `try` turned
        exactly that into a 500, for the length of a TTL, on the one endpoint whose whole
        contract is that it may serve a stale answer rather than fail.
        """
        try:
            guard("redis")
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            log.warning("cache read failed; recomputing", exc_info=True)
            return None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        try:
            guard("redis")
            await self._redis.set(key, json.dumps(value, default=_encode), ex=self._ttl)
        except Exception:
            log.warning("cache write failed; continuing", exc_info=True)
