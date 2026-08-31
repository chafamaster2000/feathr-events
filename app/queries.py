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
import re
from datetime import UTC, datetime, timedelta
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

# The live window. Ten minutes of ten-second bins is sixty numbers: fine enough that a
# burst appears where it happened, small enough to stay a summary. The cache TTL in
# config.py should track LIVE_BIN_SECONDS - a ceiling longer than a bin makes the newest
# bins of a live view the least trustworthy part of it.
LIVE_WINDOW_SECONDS = 600
LIVE_BIN_SECONDS = 10


# A suggestion prefix reaches Elasticsearch inside a regex, and it is a user's keystrokes.
# A whitelist rather than an escape list: an unescaped `.*` turns a cheap lookup into a
# scan, and a stray `(` turns it into a 400. What survives cannot mean anything but itself.
_UNSAFE_IN_PREFIX = re.compile(r"[^a-z0-9 _\-./:]")


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

    async def live_summary(
        self,
        *,
        window_seconds: int = LIVE_WINDOW_SECONDS,
        bin_seconds: int = LIVE_BIN_SECONDS,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        """A lightweight summary of recent arrivals — totals per type, plus one dense
        series of counts per bin.

        Deliberately not the same shape as `stats`. A grid of bin x type is the honest
        thing to *store*, and the wrong thing to send: sixty bins across five types is
        three hundred rows and roughly 22KB, polled every couple of seconds, for an
        endpoint whose contract is a lightweight summary. Collapsing to one array of
        totals plus one row per type is the same information at the resolution anyone can
        actually read, in a few hundred bytes.

        The series is dense and ordered oldest to newest. The aggregation only returns
        bins that hold events, so filling the gaps here rather than at the caller is what
        keeps quiet time occupying space: three scattered moments must not render as three
        consecutive ones.
        """
        # Truncated to the bin, so the window is stable for the length of one bin instead
        # of sliding with every request - which is also what lets the cache key hold.
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        end = now - timedelta(seconds=now.second % bin_seconds)
        since = end - timedelta(seconds=window_seconds)

        query = self._filter(event_type, None, None, since, None)
        rows = [
            row
            async for row in await self._col.aggregate(
                [
                    {"$match": query},
                    {
                        "$group": {
                            "_id": {
                                "bin": {
                                    "$dateTrunc": {
                                        "date": "$timestamp",
                                        "unit": "second",
                                        "binSize": bin_seconds,
                                    }
                                },
                                "event_type": "$event_type",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                ]
            )
        ]

        slots = window_seconds // bin_seconds
        series = [0] * (slots + 1)
        by_type: dict[str, int] = {}
        for row in rows:
            index = int((row["_id"]["bin"] - since).total_seconds()) // bin_seconds
            if 0 <= index < len(series):
                series[index] += row["count"]
            by_type[row["_id"]["event_type"]] = (
                by_type.get(row["_id"]["event_type"], 0) + row["count"]
            )

        return {
            "since": since,
            "window_seconds": window_seconds,
            "bin_seconds": bin_seconds,
            "total": sum(series),
            "by_type": [
                {"event_type": t, "count": c}
                for t, c in sorted(by_type.items(), key=lambda kv: -kv[1])
            ],
            "series": series,
        }

    # ---- Elasticsearch ------------------------------------------------------

    async def search(self, *, q: str, limit: int = 50) -> dict[str, Any]:
        """Full-text over what a reader would actually type: the event type, the user, the
        URL path, and anything in `metadata`.

        `event_type` and `user_id` are here because leaving them out made the box blind to
        the most obvious search in the whole domain — "signup" returned nothing while the
        index held thousands of them. They are keywords, so this is exact term matching on
        them, boosted above metadata: an event whose *type* is the word beats one that
        merely mentions it.

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
                        # Exact first, and boosted: a typo should still find the event,
                        # but never outrank the event that actually matched.
                        {"match": {"event_type": {"query": q, "boost": 5}}},
                        {"match": {"user_id": {"query": q, "boost": 4}}},
                        {"match": {"metadata": {"query": q, "boost": 3}}},
                        {"match": {"source_url.text": {"query": q, "boost": 2}}},
                        # Then the fuzzy pass. AUTO scales the allowed edit distance with
                        # term length - no edits under 3 characters, one up to 5, two
                        # beyond - so short terms do not match half the corpus.
                        #
                        # Worth knowing: this works even though `metadata` is `flattened`
                        # and therefore indexed as keywords. Verified rather than assumed:
                        # "firefx" returns zero hits without fuzziness and the same 14 as
                        # "firefox" with it.
                        {"match": {"event_type": {"query": q, "fuzziness": "AUTO"}}},
                        {"match": {"metadata": {"query": q, "fuzziness": "AUTO"}}},
                        {"match": {"source_url.text": {"query": q, "fuzziness": "AUTO"}}},
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

    async def search_terms(
        self, *, limit: int = 12, starts_with: str | None = None
    ) -> dict[str, Any]:
        """What the search box can offer: the event types, and the values in `metadata`.

        A search box over free-form metadata is unusable without this: nothing on screen
        tells the reader that "webkit-nightly" is a thing this data contains. The list is
        derived from the data rather than hard-coded, so it stays true as the data changes.

        It works *because* `metadata` is `flattened`: the whole object is indexed as one
        field whose leaves are keywords, so a terms aggregation over it returns the leaf
        values across every key at once. On a dynamically mapped object this would need one
        aggregation per key, and the set of keys is exactly what is unknown here.

        With `starts_with`, the same aggregation becomes a type-ahead: the caller gets the
        values that begin with what has been typed, with their real counts. Note the
        division of labour — this is a prefix match, deliberately, while `search` is fuzzy.
        Suggestions help you finish a word you are spelling correctly; fuzziness rescues
        you when you are not, and it does that once you submit.
        """
        agg: dict[str, Any] = {"field": "metadata", "size": limit}
        if starts_with is not None:
            cleaned = _UNSAFE_IN_PREFIX.sub("", starts_with.lower())
            if not cleaned:
                # Everything typed was dropped, so nothing can legitimately match. Falling
                # back to the global list here would answer a question nobody asked.
                return {"terms": []}
            # `include` is a regex matched against the whole term, so a prefix needs an
            # explicit tail. `.` is the one Lucene metacharacter the whitelist lets past.
            agg["include"] = cleaned.replace(".", "\\.") + ".*"

        # Two aggregations, one round trip. `event_type` is its own field, so a single
        # terms agg cannot see both — and a type-ahead that cannot complete "sig" into
        # "signup" is suggesting from half the data. `user_id` is deliberately left out:
        # forty ids of a fortieth of the corpus each would bury the five that matter.
        response = await self._es.search(
            index=self._index,
            size=0,
            aggs={"values": {"terms": agg}, "types": {"terms": {**agg, "field": "event_type"}}},
        )
        buckets = [
            *response["aggregations"]["types"]["buckets"],
            *response["aggregations"]["values"]["buckets"],
        ]
        # Deduplicated because a value could in principle live in both fields, and one row
        # per thing you can search for is the promise the panel makes.
        seen: dict[str, int] = {}
        for b in buckets:
            seen.setdefault(b["key"], b["doc_count"])

        if starts_with is None:
            # Nothing has been typed, so this list is an introduction to the data rather
            # than an answer. Ranked purely by frequency it opened with seven browsers and
            # devices and one event type — the domain's primary axis, almost entirely
            # missing from its own menu. Types lead; frequency orders the rest.
            types = {b["key"] for b in response["aggregations"]["types"]["buckets"]}
            ordered = sorted(seen.items(), key=lambda kv: (kv[0] not in types, -kv[1]))
        else:
            ordered = sorted(seen.items(), key=lambda kv: -kv[1])
        return {"terms": [{"value": value, "count": count} for value, count in ordered[:limit]]}

    # ---- helpers ------------------------------------------------------------

    @staticmethod
    def _to_output(doc: dict[str, Any]) -> dict[str, Any]:
        """`_id` is a MongoDB detail; on the outside the field is called `event_id`."""
        doc["event_id"] = doc.pop("_id")
        return doc
