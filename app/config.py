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
    # 30s introduces no lag; it puts a ceiling on lag that already exists. Ingestion is
    # asynchronous, so an accepted event is not in MongoDB yet either. See ARCHITECTURE.md §3.
    stats_cache_ttl: int = 30

    # --- App ---
    log_level: str = "INFO"


settings = Settings()
