"""Application settings. One place where the environment is read."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Connections ---
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "feathr"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "events"
    redis_url: str = "redis://localhost:6379/0"

    # --- Worker and queue ---
    # Eight, not one. The work is I/O-bound, so eight tasks mean eight events in flight
    # on a single CPU. And with one consumer, at-least-once delivery almost never
    # manifests, idempotency is never exercised and ordering never breaks: the system
    # can ship broken and still look fine. See ARCHITECTURE.md §5.
    # The ceiling is downstream: pymongo's default maxPoolSize is 100. Tests pin it to 1.
    worker_concurrency: int = 8
    worker_batch_size: int = 10
    worker_poll_interval: float = 0.05

    visibility_timeout: float = 30.0
    max_receives: int = 5
    # Bounded on purpose: an unbounded queue grows until the process dies and takes
    # everything queued with it. When full, the API answers 429.
    queue_maxsize: int = 10_000

    # --- Cache ---
    # Not a staleness ceiling any more, and worth being precise about. The live summary
    # returns only *closed* bins - the one still filling is excluded - so a cached answer
    # is not an out-of-date view of now, it is the exact answer for a window that ended.
    # The key is the bin slot, so it rolls on its own every two seconds; this TTL only
    # decides how long a superseded entry lingers before Redis drops it.
    #
    # It used to be 30s against ten-second bins, and that combination was the bug: the
    # current bin got snapshotted at its first request - usually near-empty - and served
    # that way until the key rolled, so a thousand events spread across seconds appeared
    # to arrive all at once. See ARCHITECTURE.md §3.
    stats_cache_ttl: int = 10

    # --- Rate limiting ---
    # A fairness bound, not a capacity one: `queue_maxsize` above is what defends the
    # process. At 2,000 writes per ten seconds a single client needs 50 seconds to fill
    # the queue on its own, and the worker drains it far faster - so reaching the bound
    # stays a systemic condition rather than one caller's doing. See app/ratelimit.py.
    #
    # Reads are separate and larger. The console polls `/events` every 25ms while it
    # traces one event through the pipeline, which is 40 legitimate requests a second
    # from a single address; a shared bucket would have throttled the dashboard first.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: float = 10.0
    rate_limit_writes: int = 2_000
    rate_limit_reads: int = 3_000
    # Off by default and deliberately so: the header is written by the caller, so
    # trusting it unconditionally hands every client a fresh bucket per request. Turn it
    # on only behind a proxy that overwrites it.
    rate_limit_trust_forwarded_for: bool = False

    # --- Demo ---
    # Off by default, and the destructive route is not even registered when it is off:
    # a disabled endpoint that still exists is one config mistake away from being live.
    demo_mode: bool = False

    # --- App ---
    log_level: str = "INFO"


settings = Settings()
