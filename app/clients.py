"""Infrastructure clients (MongoDB / Elasticsearch / Redis).

One place where connections are opened and closed. The rest of the app asks for clients
from here and never instantiates its own, so connection pools are shared and shutdown is
deterministic.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from elasticsearch import AsyncElasticsearch
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis

from app.config import settings
from app.faults import guard

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Clients:
    """Live handles to the three dependencies. Exactly one per process."""

    mongo: AsyncMongoClient
    redis: Redis
    elasticsearch: AsyncElasticsearch

    @property
    def db(self) -> AsyncDatabase:
        return self.mongo[settings.mongo_db]


async def connect() -> Clients:
    """Instantiate the clients. No I/O: the drivers connect lazily."""
    return Clients(
        mongo=AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5_000),
        redis=Redis.from_url(settings.redis_url, decode_responses=True),
        elasticsearch=AsyncElasticsearch(settings.elasticsearch_url, request_timeout=5),
    )


async def disconnect(clients: Clients) -> None:
    """Close everything. Each close is isolated so one failure does not block the rest."""
    for name, coro in (
        ("mongo", clients.mongo.close()),
        ("redis", clients.redis.aclose()),
        ("elasticsearch", clients.elasticsearch.close()),
    ):
        try:
            await coro
        except Exception:
            log.warning("failed closing the %s client", name, exc_info=True)


async def health(clients: Clients) -> dict[str, str]:
    """Ping the three dependencies in parallel.

    Returns "up"/"down" per dependency. Never raises: the health endpoint has to be able
    to answer even when everything is down.
    """

    async def ping_mongo() -> None:
        guard("mongodb")
        await clients.mongo.admin.command("ping")

    async def ping_redis() -> None:
        guard("redis")
        await clients.redis.ping()

    async def ping_es() -> None:
        guard("elasticsearch")
        if not await clients.elasticsearch.ping():
            raise RuntimeError("elasticsearch did not answer the ping")

    names = ("mongodb", "redis", "elasticsearch")
    results = await asyncio.gather(ping_mongo(), ping_redis(), ping_es(), return_exceptions=True)

    status: dict[str, str] = {}
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("healthcheck for %s failed: %s", name, result)
            status[name] = "down"
        else:
            status[name] = "up"
    return status
