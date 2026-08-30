"""Query layer: reads against MongoDB and Elasticsearch.

Separate from `stores.py` on purpose. Writing and reading change for different reasons:
writes are driven by the worker and care about idempotency; reads are driven by users and
care about indexes and pagination. Merging them produces a "repository" that grows
without shape.

Which store answers what is not negotiable — it is the reason for having both:

    filters and aggregations  -> MongoDB       (the source of truth, with its indexes)
    full-text over metadata   -> Elasticsearch (what MongoDB does badly)

Running full-text search against the source of truth is precisely what Elasticsearch
exists to avoid. See ARCHITECTURE.md §3.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

from elasticsearch import AsyncElasticsearch
from pymongo.asynchronous.database import AsyncDatabase

from app.stores import COLLECTION

log = logging.getLogger(__name__)

MAX_LIMIT = 500


class Bucket(StrEnum):
    """Time granularity for `/events/stats`. An enum rather than a free string: an
    invalid bucket must be a 422 from the client, not a pipeline that explodes in
    MongoDB."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


_MONGO_UNIT = {Bucket.HOURLY: "hour", Bucket.DAILY: "day", Bucket.WEEKLY: "week"}


class EventQueries:
    def __init__(self, db: AsyncDatabase, es: AsyncElasticsearch, index: str) -> None:
        self._col = db[COLLECTION]
        self._es = es
        self._index = index

    # ---- MongoDB ------------------------------------------------------------

    def _filter(
        self,
        event_type: str | None,
        user_id: str | None,
        source_url: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]:
        """Build the filter in the order the compound indexes expect.

        The indexes are {event_type, timestamp} and {user_id, timestamp} (ESR rule:
        equality first, range second). A filter that leads with `timestamp` does not use
        them; one that leads with type or user does.
        """
        f: dict[str, Any] = {}
        if event_type:
            # Normalised the same way it was on write.
            f["event_type"] = event_type.strip().lower()
        if user_id:
            f["user_id"] = user_id
        if source_url:
            f["source_url"] = source_url
        if since or until:
            window: dict[str, datetime] = {}
            if since:
                window["$gte"] = since
            if until:
                window["$lte"] = until
            f["timestamp"] = window
        return f

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        user_id: str | None = None,
        source_url: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = self._filter(event_type, user_id, source_url, since, until)
        limit = min(limit, MAX_LIMIT)

        cursor = self._col.find(query).sort("timestamp", -1).skip(offset).limit(limit)
        docs = [self._to_output(d) async for d in cursor]

        return {"items": docs, "count": len(docs), "limit": limit, "offset": offset}

    async def stats(
        self,
        *,
        bucket: Bucket = Bucket.DAILY,
        since: datetime | None = None,
        until: datetime | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        """Counts grouped by event type and time window.

        `$dateTrunc` buckets inside MongoDB. The alternative — fetching the documents and
        grouping in Python — moves data across the network only to count it, and does not
        scale with volume.
        """
        pipeline: list[dict[str, Any]] = []
        query = self._filter(event_type, None, None, since, until)
        if query:
            pipeline.append({"$match": query})

        pipeline += [
            {
                "$group": {
                    "_id": {
                        "bucket": {
                            "$dateTrunc": {"date": "$timestamp", "unit": _MONGO_UNIT[bucket]}
                        },
                        "event_type": "$event_type",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id.bucket": 1, "_id.event_type": 1}},
            {
                "$project": {
                    "_id": 0,
                    "bucket": "$_id.bucket",
                    "event_type": "$_id.event_type",
                    "count": 1,
                }
            },
        ]

        rows = [row async for row in await self._col.aggregate(pipeline)]
        return {"bucket": bucket.value, "total": sum(r["count"] for r in rows), "buckets": rows}

    # ---- Elasticsearch ------------------------------------------------------

    async def search(self, *, q: str, limit: int = 50) -> dict[str, Any]:
        """Full-text over `metadata` and the URL path.

        Known and accepted limitation: `metadata` is mapped as `flattened` to avoid
        mapping explosion (see ARCHITECTURE.md §3), and that indexes every leaf as a
        keyword. So "full-text" here is term matching, not analysis with stemming. That
        is the price of accepting unpredictable keys.
        """
        limit = min(limit, MAX_LIMIT)
        response = await self._es.search(
            index=self._index,
            size=limit,
            query={
                "bool": {
                    "should": [
                        {"match": {"metadata": q}},
                        {"match": {"source_url.text": q}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        )
        hits = response["hits"]["hits"]
        return {
            "query": q,
            "total": response["hits"]["total"]["value"],
            "items": [{"event_id": h["_id"], "score": h["_score"], **h["_source"]} for h in hits],
        }

    # ---- helpers ------------------------------------------------------------

    @staticmethod
    def _to_output(doc: dict[str, Any]) -> dict[str, Any]:
        """`_id` is a MongoDB detail; on the outside the field is called `event_id`."""
        doc["event_id"] = doc.pop("_id")
        return doc
