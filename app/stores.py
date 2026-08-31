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
        # Whether the mapping is known to be in place. Startup tolerates `ensure_schema`
        # failing, so this cannot be assumed from the fact that the app is running.
        self._ready = False

    async def index(self, event: Event) -> None:
        """Also idempotent: the document `_id` is the `event_id`."""
        guard("elasticsearch")
        # Never write into an index that might not exist yet. Elasticsearch creates one
        # on first write by default, with a *dynamic* mapping, and that is the failure
        # §3 spends pages preventing: `event_type` comes out `text` instead of `keyword`,
        # so the exact-term boost and every aggregation over it stop working, and
        # `metadata` comes out as one field per key - the mapping explosion `flattened`
        # exists to avoid. Verified against this cluster rather than assumed.
        #
        # The sequence that reached it: Elasticsearch unreachable at startup, which the
        # lifespan deliberately tolerates so a schema problem does not become an outage;
        # Elasticsearch recovers; the worker's first write auto-creates. Nothing detects
        # it, no restart heals it - `ensure_schema` sees an index and returns - and the
        # only recovery is a person knowing to run `scripts/reindex.py --recreate`.
        #
        # One `exists` call, once, and never again after it succeeds. The startup path is
        # allowed to fail; this one is not.
        if not self._ready:
            await self.ensure_schema()
        doc = event.model_dump(mode="json")
        doc.pop("event_id")
        await self._es.index(index=self._index, id=event.event_id, document=doc)

    async def ensure_schema(self) -> None:
        """The template first, then the index.

        The template is not redundant with the create below. It is what makes an
        auto-created index correct anyway - if the index is deleted, if `/demo/reset`
        races a worker between its delete and its create, if anything at all writes
        before this runs. `create` fixes the expected path; the template fixes the
        unexpected ones, which is where the dynamic mapping actually came from.
        """
        await self._es.indices.put_index_template(
            name=f"{self._index}-template",
            index_patterns=[self._index],
            template={"mappings": INDEX_MAPPING},
        )
        if await self._es.indices.exists(index=self._index):
            await self._warn_if_the_mapping_is_wrong()
        else:
            await self._es.indices.create(index=self._index, mappings=INDEX_MAPPING)
            log.info("created elasticsearch index: %s", self._index)
        self._ready = True

    async def _warn_if_the_mapping_is_wrong(self) -> None:
        """Say so rather than repair it.

        An index that already exists with the wrong mapping holds real documents, and
        deleting it to fix a mapping is a decision an application should never take on
        its own. What it *can* do is stop the condition being silent: before this, a
        dynamically-mapped index looked exactly like a healthy one from the outside -
        searches simply returned different results, with no error anywhere.
        """
        try:
            mapping = await self._es.indices.get_mapping(index=self._index)
            properties = next(iter(mapping.body.values()))["mappings"]["properties"]
            found = properties.get("event_type", {}).get("type")
        except (KeyError, StopIteration, TypeError):  # a mapping we cannot read is not a verdict
            return
        if found != "keyword":
            log.error(
                "elasticsearch index %s has event_type mapped as %r, not 'keyword'. It was "
                "created dynamically rather than from INDEX_MAPPING, so metadata is not "
                "flattened either: exact-type matching and every aggregation over it are "
                "wrong. Run scripts/reindex.py --recreate. See ARCHITECTURE.md §3.",
                self._index,
                found,
            )
