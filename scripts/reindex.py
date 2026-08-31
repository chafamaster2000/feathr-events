#!/usr/bin/env python3
"""Rebuild the Elasticsearch index from MongoDB.

ARCHITECTURE.md claims Elasticsearch is a *derived* index — that losing it is lag rather
than data loss, because it can be rebuilt from the source of truth. This is the script
that makes that claim true instead of aspirational.

It is the recovery path for the failure the architecture document spends most time on:
the worker writes MongoDB and Elasticsearch without a transaction between them, so a
failed second write leaves an event that exists but cannot be found. Retries close that
window in normal operation; this closes it after a longer outage, or after the index is
deleted outright.

There is deliberately no reverse direction. Nothing rebuilds MongoDB from Elasticsearch,
because that would make the derived index authoritative for something — and the moment
two stores are both authoritative, neither is.

Usage:
    python3 scripts/reindex.py              # rebuild in place
    python3 scripts/reindex.py --recreate   # drop the index first, re-apply the mapping
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Run as a plain script (`python3 scripts/reindex.py`), the repository root is not on
# sys.path - only pytest puts it there, via `pythonpath` in pyproject.toml. Recovery
# tooling should not require a particular invocation to work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import clients
from app.config import settings
from app.models import Event
from app.stores import COLLECTION, ElasticEventIndex

BATCH = 500


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--recreate",
        action="store_true",
        help="delete the index and re-apply the mapping before reindexing",
    )
    args = ap.parse_args()

    handles = await clients.connect()
    index = ElasticEventIndex(handles.elasticsearch, settings.elasticsearch_index)
    started = time.perf_counter()
    done = errors = 0

    try:
        total = await handles.db[COLLECTION].count_documents({})
        print(f"source of truth: {total} documents in mongodb.{COLLECTION}")

        if args.recreate:
            await handles.elasticsearch.options(ignore_status=404).indices.delete(
                index=settings.elasticsearch_index
            )
            print(f"dropped index {settings.elasticsearch_index}")
        await index.ensure_schema()

        cursor = handles.db[COLLECTION].find({})
        async for doc in cursor:
            doc["event_id"] = doc.pop("_id")
            try:
                # Reuses the same adapter the worker uses, so the document shape cannot
                # drift between the live path and the recovery path.
                await index.index(Event(**doc))
                done += 1
            except Exception as exc:  # noqa: BLE001 - one bad document must not stop recovery
                errors += 1
                print(f"  skipped {doc.get('event_id')}: {exc}", file=sys.stderr)
            if done % BATCH == 0 and done:
                print(f"  {done}/{total}")

        await handles.elasticsearch.indices.refresh(index=settings.elasticsearch_index)
        count = (await handles.elasticsearch.count(index=settings.elasticsearch_index))["count"]
        elapsed = time.perf_counter() - started
        print(f"\nreindexed {done} in {elapsed:.1f}s   errors {errors}")
        print(
            f"mongodb {total}  ->  elasticsearch {count}   "
            f"{'in sync' if count == total else 'MISMATCH'}"
        )
        return 0 if count == total and errors == 0 else 1
    finally:
        await clients.disconnect(handles)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
