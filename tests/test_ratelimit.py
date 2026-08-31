"""The limiter's arithmetic, and the one property the console depends on.

The interesting tests here are not "does it refuse" - a token bucket that refuses is
trivial. They are the two ways this feature can be wrong in a way nobody notices: it
throttles legitimate traffic, or it can be walked around.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.ratelimit import (
    LOG_EVERY_SECONDS,
    MAX_CLIENTS,
    RateLimiter,
    RateLimitMiddleware,
    classify,
    client_of,
)


class FakeClock:
    """Time as a variable. A limiter tested with the wall clock either sleeps or flakes."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def limiter(clock: FakeClock, *, writes: int = 10, reads: int = 20) -> RateLimiter:
    return RateLimiter(writes=writes, reads=reads, window_seconds=10.0, clock=clock)


# --- the bucket ------------------------------------------------------------------------


def test_grants_the_full_capacity_then_refuses() -> None:
    clock = FakeClock()
    rl = limiter(clock)

    assert all(rl.check("1.2.3.4", "write") == 0.0 for _ in range(10))

    wait = rl.check("1.2.3.4", "write")
    assert wait > 0.0


def test_a_refused_client_is_told_a_wait_that_is_actually_enough() -> None:
    """`Retry-After` is a promise. Coming back at the stated time must work."""
    clock = FakeClock()
    rl = limiter(clock)
    for _ in range(10):
        rl.check("1.2.3.4", "write")

    wait = rl.check("1.2.3.4", "write")
    clock.advance(wait)

    assert rl.check("1.2.3.4", "write") == 0.0


def test_tokens_refill_at_the_configured_rate() -> None:
    clock = FakeClock()
    rl = limiter(clock)  # 10 writes / 10s = one per second
    for _ in range(10):
        rl.check("1.2.3.4", "write")

    clock.advance(3.0)

    assert sum(1 for _ in range(3) if rl.check("1.2.3.4", "write") == 0.0) == 3
    assert rl.check("1.2.3.4", "write") > 0.0


def test_the_bucket_never_fills_past_capacity() -> None:
    """Otherwise an idle client banks credit and the limit stops being a limit."""
    clock = FakeClock()
    rl = limiter(clock)
    rl.check("1.2.3.4", "write")

    clock.advance(3_600.0)

    assert sum(1 for _ in range(10) if rl.check("1.2.3.4", "write") == 0.0) == 10
    assert rl.check("1.2.3.4", "write") > 0.0


def test_clients_do_not_share_a_bucket() -> None:
    clock = FakeClock()
    rl = limiter(clock)
    for _ in range(10):
        rl.check("noisy", "write")

    assert rl.check("quiet", "write") == 0.0


# --- the property the dashboard depends on ---------------------------------------------


def test_a_write_flood_does_not_throttle_reads() -> None:
    """Separate buckets, and this is why they are separate.

    Ingesting and observing are different activities. Sharing one bucket would mean a
    burst of five hundred events silences the very views that exist to show what happened
    to it - the failure would look like a broken dashboard, not like a rate limit.
    """
    clock = FakeClock()
    rl = limiter(clock)
    for _ in range(50):
        rl.check("1.2.3.4", "write")

    assert rl.check("1.2.3.4", "read") == 0.0


def test_the_consoles_own_polling_rate_stays_under_the_read_limit() -> None:
    """The dashboard traces one event by polling `/events` every 25ms for up to 15s.

    That is 40 requests a second from a single address, and every one of them is
    legitimate. Vite proxies the browser, so the whole console arrives as one client and
    shares one bucket. This test pins the real numbers - `useTrace.POLL_MS` and its
    `TIMEOUT_MS` - against the configured limit, so lowering the limit without noticing
    fails here rather than in the browser.
    """
    clock = FakeClock()
    rl = RateLimiter(
        writes=settings.rate_limit_writes,
        reads=settings.rate_limit_reads,
        window_seconds=settings.rate_limit_window_seconds,
        clock=clock,
    )

    refused = 0
    for _ in range(15 * 40):  # POLL_MS = 25 for TIMEOUT_MS = 15_000
        if rl.check("127.0.0.1", "read") > 0.0:
            refused += 1
        clock.advance(0.025)

    assert refused == 0


def test_a_full_burst_from_the_console_is_never_rate_limited() -> None:
    """The largest button is 500, fired at 25 concurrent posts - about a second's work.

    A limiter that refuses the product's own demonstration is worse than no limiter: the
    reader cannot tell backpressure from throttling, which is the confusion the
    `X-Throttle-Reason` header exists to prevent in the first place.
    """
    clock = FakeClock()
    rl = RateLimiter(
        writes=settings.rate_limit_writes,
        reads=settings.rate_limit_reads,
        window_seconds=settings.rate_limit_window_seconds,
        clock=clock,
    )

    for _ in range(4):  # four back-to-back bursts, no pause between them
        assert all(rl.check("127.0.0.1", "write") == 0.0 for _ in range(500))
        clock.advance(1.0)


# --- classification and identity -------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/events", "write"),
        ("GET", "/events", "read"),
        ("GET", "/events/search", "read"),
        # Rate limiting a liveness probe turns a busy minute into a restart loop.
        ("GET", "/health", None),
        ("POST", "/demo/fault", None),
        ("GET", "/docs", None),
    ],
)
def test_classification(method: str, path: str, expected: str | None) -> None:
    assert classify(method, path) == expected


def test_forwarded_for_is_ignored_unless_it_is_trusted() -> None:
    """The header is caller-written. Honouring it by default defeats the whole feature.

    An attacker sending a different `X-Forwarded-For` per request would hold a fresh
    bucket every time and never be limited at all.
    """
    scope = {
        "client": ("10.0.0.1", 5000),
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")],
    }

    assert client_of(scope, trust_forwarded_for=False) == "10.0.0.1"
    assert client_of(scope, trust_forwarded_for=True) == "203.0.113.9"


def test_a_missing_client_still_gets_a_bucket() -> None:
    """ASGI does not promise `client`. Falling over here would 500 every request."""
    assert client_of({"client": None, "headers": []}, trust_forwarded_for=False) == "unknown"


def test_the_bucket_table_stays_bounded() -> None:
    """The table is keyed by a value the caller controls, so it is an abuse surface too.

    One address per packet and the limiter becomes the memory exhaustion it exists to
    prevent.
    """
    clock = FakeClock()
    rl = limiter(clock)

    for i in range(MAX_CLIENTS + 500):
        rl.check(f"10.0.{i // 256}.{i % 256}", "write")

    assert len(rl._buckets) <= MAX_CLIENTS


# --- the HTTP surface ------------------------------------------------------------------


async def _stub(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.anyio
async def test_the_refusal_is_a_429_that_says_which_kind_it_is() -> None:
    """Two refusals share this status. Without the marker they are indistinguishable.

    `POST /events` also answers 429 when the queue is full, and the console counts those
    as backpressure. A throttled request counted the same way would be read as the
    pipeline saturating when in fact one client was simply impatient.
    """
    clock = FakeClock()
    app = RateLimitMiddleware(_stub, limiter(clock, writes=2), trust_forwarded_for=False)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.post("/events")).status_code == 200
        assert (await http.post("/events")).status_code == 200

        refused = await http.post("/events")

    assert refused.status_code == 429
    assert refused.headers["x-throttle-reason"] == "rate_limit"
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.headers["x-ratelimit-limit"] == "2"


@pytest.mark.anyio
async def test_health_is_never_refused_however_hard_it_is_polled() -> None:
    clock = FakeClock()
    app = RateLimitMiddleware(_stub, limiter(clock, reads=2), trust_forwarded_for=False)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        codes = [(await http.get("/health")).status_code for _ in range(20)]

    assert codes == [200] * 20


def test_the_limiter_does_not_become_the_flood() -> None:
    """A line per refusal hands the attacker unbounded writes to the operator's disk.

    Found by the log harness, not by reading the code: one flood produced 1,651 identical
    WARN lines, which is both a write amplification granted by the defence itself and the
    end of the log's usefulness for finding anything else. One line per client per window,
    carrying the count it stands for, says strictly more.
    """
    clock = FakeClock()
    rl = limiter(clock, writes=1)
    rl.check("1.2.3.4", "write")

    lines = [n for _ in range(500) if (n := rl.should_log("1.2.3.4", "write")) is not None]
    for _ in range(500):
        rl.check("1.2.3.4", "write")

    assert len(lines) == 1
    assert lines[0] == 1  # the first refusal is reported immediately

    clock.advance(LOG_EVERY_SECONDS)
    rl.check("1.2.3.4", "write")

    # The next line accounts for everything the first one silenced, so no refusal is lost
    # from the record - only the repetition is.
    assert rl.should_log("1.2.3.4", "write") == 500


def test_a_second_client_is_reported_on_its_own_schedule() -> None:
    """Otherwise one noisy address suppresses the line that would name a different one."""
    clock = FakeClock()
    rl = limiter(clock, writes=1)
    for who in ("noisy", "other"):
        rl.check(who, "write")
        rl.check(who, "write")

    assert rl.should_log("noisy", "write") == 1
    assert rl.should_log("other", "write") == 1
