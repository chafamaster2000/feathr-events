#!/usr/bin/env python3
"""Seed the platform with realistic events, through the public API.

Writes with `POST /events` rather than straight into MongoDB, deliberately. Writing to
the stores directly would be faster and would prove nothing: it would skip the queue, the
worker, the idempotent upsert and the Elasticsearch write — the whole system under test.
Going through the API means the seed run *is* an end-to-end exercise, and the queue depth
chart in the console has something real to show.

Two properties of the generated data are not decoration:

  * **Back-dated timestamps.** The API accepts a client-supplied `timestamp`, so events
    are spread across several days. With everything stamped "now", the daily bucket in
    /events/stats is a single bar and the hourly one is meaningless.
  * **Heterogeneous metadata keys per event type.** A conversion carries `amount` and
    `currency`, a signup carries `plan`, an error carries `code` and `retryable`. This is
    exactly the shape that makes a dynamic Elasticsearch mapping explode, and the reason
    `metadata` is mapped `flattened`. The seed data demonstrates the mapping decision.

Usage:
    python3 scripts/seed.py                      # 2000 events over 7 days
    python3 scripts/seed.py --count 500 --days 2
    python3 scripts/seed.py --api http://localhost:5173/api
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta

import httpx

# Proportions a real analytics stream roughly has: most traffic is passive.
EVENT_MIX = [
    ("pageview", 60),
    ("click", 22),
    ("add_to_cart", 9),
    ("conversion", 5),
    ("signup", 3),
    ("error", 1),
]
BROWSERS = ["chrome", "firefox", "safari", "edge", "webkit-nightly"]
DEVICES = ["mobile", "desktop", "tablet"]
COUNTRIES = ["us", "ar", "es", "br", "de", "jp"]
CAMPAIGNS = ["spring-sale", "retargeting", "newsletter", "organic", "paid-social"]
PLANS = ["free", "pro", "enterprise"]
PATHS = ["/product/{n}", "/category/shoes", "/category/outerwear", "/checkout", "/search", "/"]


def weighted_type(rng: random.Random) -> str:
    total = sum(w for _, w in EVENT_MIX)
    roll = rng.uniform(0, total)
    upto = 0.0
    for name, weight in EVENT_MIX:
        upto += weight
        if roll <= upto:
            return name
    return EVENT_MIX[0][0]


def make_user(rng: random.Random) -> str:
    """Long tail: a few users generate a lot of traffic, most generate a little.

    A uniform distribution makes filtering by user uninteresting — every user looks the
    same. This way `?user_id=u-3` returns something worth looking at.
    """
    if rng.random() < 0.30:
        return f"u-{rng.randint(0, 9)}"  # the heavy 30%
    return f"u-{rng.randint(10, 400)}"


def make_event(rng: random.Random, days: int) -> dict:
    event_type = weighted_type(rng)
    # Skewed towards recent: more traffic today than a week ago.
    age_days = days * (rng.random() ** 1.7)
    when = datetime.now(UTC) - timedelta(
        days=age_days, hours=rng.uniform(0, 24), minutes=rng.uniform(0, 60)
    )

    metadata: dict[str, object] = {
        "browser": rng.choice(BROWSERS),
        "device": rng.choice(DEVICES),
        "country": rng.choice(COUNTRIES),
    }
    if rng.random() < 0.4:
        metadata["campaign"] = rng.choice(CAMPAIGNS)
    # Keys that exist only for some event types - the flattened-mapping case.
    if event_type == "conversion":
        metadata |= {"amount": round(rng.uniform(9, 480), 2), "currency": "usd"}
    elif event_type == "signup":
        metadata |= {"plan": rng.choice(PLANS), "referred": rng.random() < 0.3}
    elif event_type == "error":
        metadata |= {
            "code": rng.choice(["E_TIMEOUT", "E_PAYMENT", "E_STOCK"]),
            "retryable": rng.random() < 0.6,
        }
    elif event_type == "add_to_cart":
        metadata |= {"quantity": rng.randint(1, 4)}

    return {
        "event_type": event_type,
        "user_id": make_user(rng),
        "source_url": "https://shop.example.com" + rng.choice(PATHS).format(n=rng.randint(1, 240)),
        "timestamp": when.isoformat(),
        "metadata": metadata,
    }


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--count", type=int, default=2000, help="events to send. default: 2000")
    ap.add_argument("--days", type=int, default=7, help="days to spread them over. default: 7")
    ap.add_argument("--api", default="http://localhost:8000", help="API base url")
    ap.add_argument("--concurrency", type=int, default=25, help="requests in flight. default: 25")
    ap.add_argument("--seed", type=int, default=None, help="rng seed, for a reproducible run")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    sent = refused = failed = 0
    gate = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(base_url=args.api, timeout=15.0) as client:
        try:
            health = (await client.get("/health")).json()
        except httpx.HTTPError as exc:
            print(f"cannot reach the API at {args.api}: {exc}", file=sys.stderr)
            print("is the stack up?  make up", file=sys.stderr)
            return 2
        print(f"api: {health['status']}  deps: {health['dependencies']}")
        print(f"seeding {args.count} events across {args.days} days...")

        async def one() -> None:
            nonlocal sent, refused, failed
            async with gate:
                try:
                    r = await client.post("/events", json=make_event(rng, args.days))
                except httpx.HTTPError:
                    failed += 1
                    return
                if r.status_code == 202:
                    sent += 1
                elif r.status_code == 429:
                    refused += 1  # backpressure working as designed
                else:
                    failed += 1

        await asyncio.gather(*(one() for _ in range(args.count)))

        # The API accepted them; the worker still has to drain the queue.
        print("waiting for the worker to drain the queue...")
        for _ in range(600):
            q = (await client.get("/health")).json()["queue"]
            if q["visible"] == 0 and q["in_flight"] == 0:
                break
            await asyncio.sleep(0.25)

        final = (await client.get("/health")).json()
        print(f"\naccepted {sent}   refused(429) {refused}   failed {failed}")
        print(f"queue    {final['queue']}")
        print(f"worker   {final['worker']}")
        if final["queue"]["dlq"]:
            print(f"warning: {final['queue']['dlq']} events reached the dead-letter queue")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
