"""Persistence ports and their real adapters.

Two narrow ports, one per responsibility:

    EventStore  -> MongoDB, the SOURCE OF TRUTH. Losing something here is data loss.
    EventIndex  -> Elasticsearch, a DERIVED INDEX. Losing something here is lag:
                   it can be rebuilt from MongoDB.

That asymmetry is not decoration: it is what lets the worker avoid a distributed
transaction. See ARCHITECTURE.md §3.

The worker depends on these Protocols, not on pymongo or elasticsearch. That is what
makes it possible to test the retry logic with doubles, without starting any database.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from elasticsearch import AsyncElasticsearch
from pymongo.asynchronous.database import AsyncDatabase

from app.faults import guard
from app.models import Event

log = logging.getLogger(__name__)

COLLECTION = "events"

# Explicit mapping: without it Elasticsearch infers types and `event_type` ends up as
# analysed `text`, which breaks aggregations. See ARCHITECTURE.md §3.
INDEX_MAPPING: dict[str, Any] = {
    "properties": {
        # keyword, NOT text: nobody runs full-text over "pageview". It is filtered
        # exactly and grouped; `text` would tokenize it and aggregations would stop
        # being useful.
        "event_type": {"type": "keyword"},
        "user_id": {"type": "keyword"},
        "timestamp": {"type": "date"},
        "received_at": {"type": "date"},
        # Multi-field: group by exact URL, and also search path tokens.
        "source_url": {"type": "keyword", "fields": {"text": {"type": "text"}}},
        # The hard field. Under dynamic mapping, arbitrary JSON creates a field per new
        # key and the cluster degrades (mapping explosion). `flattened` maps the whole
        # object as a single field and indexes its leaves as keywords.
        # The cost: numeric ranges, highlighting and type-aware sorting are lost inside
        # metadata. That is the price of accepting unpredictable keys.
        "metadata": {"type": "flattened"},
    }
}


class EventStore(Protocol):
    """The source of truth."""

    async def upsert(self, event: Event) -> None: ...
    async def ensure_schema(self) -> None: ...


class EventIndex(Protocol):
    """The derived index."""

    async def index(self, event: Event) -> None: ...
    async def ensure_schema(self) -> None: ...


class MongoEventStore:
    """MongoDB. Every write is an upsert by `_id`, never an insert."""

    def __init__(self, db: AsyncDatabase) -> None:
        self._col = db[COLLECTION]

    async def upsert(self, event: Event) -> None:
        """Idempotent by construction.

        `_id` is the `event_id`, so reprocessing the same delivery rewrites the same
        document with the same content. This is what makes the queue's at-least-once
        delivery safe: duplicates are normal, not an error.
        """
        doc = event.to_document()
        guard("mongodb")
        await self._col.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def ensure_schema(self) -> None:
        """Indexes derived from the actual query patterns.

        ESR rule: equality first, then range/sort. Reversed, MongoDB scans the whole
        range and filters afterwards.
        """
        await self._col.create_index([("event_type", 1), ("timestamp", -1)], name="type_time")
        await self._col.create_index([("user_id", 1), ("timestamp", -1)], name="user_time")
        # `timestamp` alone earns its place now, and did not before. The argument against
        # it was that it is already the suffix of both compound indexes — true, and useless
        # to a query that leads with it, because a suffix is not a prefix (ESR again). It
        # was harmless while every read filtered by type or by user first. The live stats
        # window filters by time and nothing else, and a view that polls it every two
        # seconds was scanning the whole collection to do it: measured at 620 documents
        # examined and 0 index keys.
        await self._col.create_index([("timestamp", -1)], name="time_desc")
        # Still deliberately absent: `metadata.*` (an open key space — that is what
        # Elasticsearch is for) and `source_url` alone (low selectivity). Every extra index
        # is a slower write on the hot path.


class ElasticEventIndex:
    """Elasticsearch. Fully rebuildable from MongoDB."""

    def __init__(self, es: AsyncElasticsearch, index: str) -> None:
        self._es = es
        self._index = index

    async def index(self, event: Event) -> None:
        """Also idempotent: the document `_id` is the `event_id`."""
        doc = event.model_dump(mode="json")
        doc.pop("event_id")
        guard("elasticsearch")
        await self._es.index(index=self._index, id=event.event_id, document=doc)

    async def ensure_schema(self) -> None:
        if await self._es.indices.exists(index=self._index):
            return
        await self._es.indices.create(index=self._index, mappings=INDEX_MAPPING)
        log.info("created elasticsearch index: %s", self._index)
