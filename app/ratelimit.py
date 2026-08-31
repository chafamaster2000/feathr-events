"""Rate limiting: a token bucket per client, in front of writes and reads separately.

This is not backpressure. The queue's bound already does that job, and it answers 429
too — see `POST /events` in `main.py`. The two are different questions and the
`X-Throttle-Reason` header says which one refused:

    queue_full   the system is at capacity. Everyone sees it. Retrying helps.
    rate_limit   *you* are asking too fast. Nobody else sees it. Slowing down helps.

Collapsing them would make the console's burst report unreadable: it counts 429s as
evidence of backpressure, and a limiter that borrowed the same status with no marker
would turn "your own client is impatient" into "the pipeline is saturated".

**Why the limits are where they are.** `queue_maxsize` is 10,000. At 2,000 writes per
ten seconds a single client needs 50 seconds of uninterrupted effort to fill the queue
alone, and the worker drains it far faster than that. So the limit buys a specific
property: reaching the queue's bound is a *systemic* condition, never one caller's doing.
That is the number's justification, not a guess at a comfortable ceiling.

Reads get their own, larger bucket. They are cheap, one of them is cached, and the
console polls `/events` every 25ms while tracing a single event through the pipeline —
40 requests a second, from one address, entirely legitimately. A shared bucket would have
made the dashboard the first thing the limiter throttled.

**In-process, like the queue, and for the same reason.** N processes would be N limiters
each granting the full rate, which is the same silent multiplication ARCHITECTURE §5
refuses for the queue — and `_refuse_multiple_processes()` already forbids the
configuration that would cause it. Redis is deliberately not used here: the cache is an
optimisation the system runs without (§6 verifies it), and putting the limiter there
would make Redis load-bearing for ingestion.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

log = logging.getLogger(__name__)

Kind = Literal["read", "write"]

# Neither a probe nor the fault controls are throttled. Rate limiting a liveness check is
# how a busy minute becomes a restart loop: the orchestrator asks "are you alive", the
# limiter says 429, and the answer to a question nobody rationed is taken as death.
EXEMPT_PREFIXES = ("/health", "/demo", "/docs", "/redoc", "/openapi.json")

# A table keyed by a value the caller controls is itself an abuse surface: one address per
# packet and the limiter becomes the memory exhaustion it exists to prevent. Bounded, and
# evicted by idleness first — a full bucket is a client that stopped asking.
MAX_CLIENTS = 4_096


# The limiter must not become the flood. One line per refusal means a client sending
# 1,651 rejected requests writes 1,651 identical WARN lines to disk - unbounded writing,
# granted by the very thing meant to bound it, and the operator loses the log they use to
# find every other problem. One line per client per window, carrying the count of what it
# stands for, says strictly more and costs nothing.
LOG_EVERY_SECONDS = 10.0


@dataclass
class Bucket:
    """Tokens, and the moment they were last counted.

    Refill is computed on read rather than on a timer: a bucket nobody asks about costs
    nothing, and there is no sweep to schedule.
    """

    tokens: float
    updated: float
    # Refusals since the last line written about this client. Not a counter of all
    # refusals - it resets when it is reported, because its only job is to say how many
    # the one printed line represents.
    suppressed: int = 0
    logged_at: float = 0.0

    def take(self, *, capacity: int, per_second: float, now: float) -> float:
        """Spend one token. Returns the seconds to wait, or 0.0 when it was granted."""
        self.tokens = min(capacity, self.tokens + (now - self.updated) * per_second)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / per_second


class RateLimiter:
    """The buckets, and the arithmetic. No HTTP in here — that is the middleware's job."""

    def __init__(
        self,
        *,
        writes: int,
        reads: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity: dict[Kind, int] = {"write": writes, "read": reads}
        self._rate: dict[Kind, float] = {
            "write": writes / window_seconds,
            "read": reads / window_seconds,
        }
        self._clock = clock
        self._buckets: OrderedDict[tuple[str, Kind], Bucket] = OrderedDict()

    def check(self, client: str, kind: Kind) -> float:
        """0.0 when the request may proceed, otherwise the seconds until it could."""
        now = self._clock()
        key = (client, kind)
        bucket = self._buckets.get(key) or Bucket(tokens=float(self._capacity[kind]), updated=now)
        self._buckets[key] = bucket
        self._buckets.move_to_end(key)
        # Spend first, evict after. A bucket is created full, and eviction reads "full" as
        # "idle" - so evicting before the token is taken deletes the caller that is asking
        # right now, and every request from a new client lands in a fresh bucket that
        # never remembers the last one. The limit would apply to nobody.
        wait = bucket.take(capacity=self._capacity[kind], per_second=self._rate[kind], now=now)
        self._evict_if_needed()
        return wait

    def should_log(self, client: str, kind: Kind) -> int | None:
        """`None` to stay quiet, otherwise how many refusals this line stands for."""
        bucket = self._buckets.get((client, kind))
        if bucket is None:
            return None
        bucket.suppressed += 1
        now = self._clock()
        if now - bucket.logged_at < LOG_EVERY_SECONDS:
            return None
        bucket.logged_at = now
        count, bucket.suppressed = bucket.suppressed, 0
        return count

    def remaining(self, client: str, kind: Kind) -> int:
        bucket = self._buckets.get((client, kind))
        return self._capacity[kind] if bucket is None else int(bucket.tokens)

    def limit(self, kind: Kind) -> int:
        return self._capacity[kind]

    def _evict_if_needed(self) -> None:
        """Drop idle clients first, then the least recently seen.

        A bucket back at full capacity is a client that stopped asking, so forgetting it
        loses nothing: recreating it produces exactly the same state. Only when every
        bucket is in use does eviction start costing accuracy, and then LRU is the least
        wrong order — the client evicted is the one that has been quiet longest.
        """
        if len(self._buckets) <= MAX_CLIENTS:
            return
        for key, bucket in list(self._buckets.items()):
            if bucket.tokens >= self._capacity[key[1]]:
                del self._buckets[key]
            if len(self._buckets) <= MAX_CLIENTS:
                return
        while len(self._buckets) > MAX_CLIENTS:
            self._buckets.popitem(last=False)


def classify(method: str, path: str) -> Kind | None:
    """`None` means "not subject to a limit"."""
    if path.startswith(EXEMPT_PREFIXES):
        return None
    return "write" if method in ("POST", "PUT", "PATCH", "DELETE") else "read"


def client_of(scope: dict[str, Any], *, trust_forwarded_for: bool) -> str:
    """The address the bucket belongs to.

    `X-Forwarded-For` is trusted only when configured, and that default is the whole
    point: the header is written by the caller, so honouring it unconditionally lets
    anyone hold a fresh bucket per request and defeat the limiter completely. It is
    a deployment fact rather than a default.

    And when it is trusted, the **rightmost** entry is the one to take, not the leftmost.
    The list grows left to right as it is forwarded, so the leftmost entry is whatever the
    original client wrote — the one value an attacker fully controls — while the rightmost
    was appended by the nearest proxy. Taking the leftmost is the classic spoof, and it
    fails in exactly the deployment this setting exists for: nginx's
    `proxy_add_x_forwarded_for` *appends*, so turning the knob on with a leftmost read
    would have converted a hardened limiter into no limiter at all.
    """
    if trust_forwarded_for:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if forwarded := headers.get("x-forwarded-for"):
            return forwarded.rsplit(",", 1)[-1].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Pure ASGI, like the logger beside it, so streaming responses are unaffected."""

    def __init__(self, app: Any, limiter: RateLimiter, *, trust_forwarded_for: bool) -> None:
        self.app = app
        self.limiter = limiter
        self.trust_forwarded_for = trust_forwarded_for

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        kind = classify(scope.get("method", "GET"), scope.get("path", ""))
        if kind is None:
            await self.app(scope, receive, send)
            return

        client = client_of(scope, trust_forwarded_for=self.trust_forwarded_for)
        wait = self.limiter.check(client, kind)
        if wait == 0.0:
            await self.app(scope, receive, send)
            return

        # Ceiling, not round: a `Retry-After` that rounds 1.4s down to 1 invites the
        # client back before the token exists, and a refusal that repeats is worse than
        # one that waits.
        retry_after = max(1, -(-wait // 1))
        if (refusals := self.limiter.should_log(client, kind)) is not None:
            log.warning(
                "rate limit: %d %s request(s) refused from %s in the last %gs, "
                "most recently %s %s. Retry in %ss",
                refusals,
                kind,
                client,
                LOG_EVERY_SECONDS,
                scope.get("method"),
                scope.get("path"),
                retry_after,
            )
        await self._refuse(send, kind=kind, retry_after=int(retry_after))

    async def _refuse(self, send: Any, *, kind: Kind, retry_after: int) -> None:
        body = json.dumps({"detail": f"too many {kind} requests, retry in {retry_after}s"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(retry_after).encode()),
                    # The marker that keeps this 429 distinguishable from the queue's.
                    (b"x-throttle-reason", b"rate_limit"),
                    (b"x-ratelimit-limit", str(self.limiter.limit(kind)).encode()),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
