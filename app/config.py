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
    # Ten seconds, because that is the live bin. `/events/stats/realtime` serves
    # ten-second bins, so a longer ceiling makes the newest bins of a *live* chart the
    # least trustworthy part of it - at 30s the three rightmost bins could each be missing
    # arrivals, and the right edge is exactly where the eye goes. At ten, the only
    # unsettled bin is the current one, which is incomplete anyway because it is still
    # filling. Going lower buys freshness with nowhere to show up.
    #
    # This number should track the LIVE bin size in queries.py. If that changes, change
    # this. See ARCHITECTURE.md §3.
    #
    # An earlier comment here claimed 30s "introduces no lag; it puts a ceiling on lag that
    # already exists". Measured, the pipeline's own lag from POST to visible in MongoDB is
    # 2-48ms - so the cache was not a ceiling on existing lag, it was six hundred times it,
    # and by far the dominant staleness in the read path.
    stats_cache_ttl: int = 10

    # --- Demo ---
    # Off by default, and the destructive route is not even registered when it is off:
    # a disabled endpoint that still exists is one config mistake away from being live.
    demo_mode: bool = False

    # --- App ---
    log_level: str = "INFO"


settings = Settings()
