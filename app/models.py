"""Domain models.

The brief defines five event fields: type, timestamp, user_id, source_url and metadata.
The `event_id` is **not** in the brief — we added it, and *where* it is assigned is what
makes everything else work.

    API assigns id -> enqueue -> worker      a redelivery carries the SAME id     OK
    API enqueues -> worker assigns id        every redelivery invents a NEW id    broken

If the id were born in the worker, the unique index would deduplicate nothing: the same
event redelivered would look like two distinct events. That is why `Event.from_input()` is
called in the HTTP layer, before the queue is touched. See ARCHITECTURE.md §2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def _now() -> datetime:
    return datetime.now(UTC)


# How far ahead of the server a client clock may be before its timestamp is refused.
# Generous enough for unsynchronised machines, far short of useful for back-dating the
# top of a listing.
FUTURE_SKEW = timedelta(minutes=5)


class EventIn(BaseModel):
    """What a client sends to POST /events.

    It deliberately does not include `event_id`: the client does not choose it. If it
    did, two clients could collide and one would overwrite the other's event.
    """

    # An unexpected field is a client error, not something to swallow silently.
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    # Optional: if the client does not know when it happened, the API stamps it.
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _bound_the_future(cls, v: datetime | None) -> datetime | None:
        """A client may say when an event happened, but not that it happens later.

        Back-dating is legitimate: a buffered or offline client sends late, and the
        pipeline is built so a late arrival still lands where it belongs. Forward-dating
        is not. The field is unvalidated no longer because an unbounded future timestamp
        is not a typo, it is a lever: sorted descending, one event dated 2031 sits at the
        top of every listing until somebody deletes it by hand, and it opens a bucket
        five years wide in every aggregation. Observed exactly that way, from a probe.

        The whole concurrency argument also rests on this field. `timestamp` travels
        inside the event so that write order cannot change the outcome, which means any
        caller can move where an event lands. Accepting the past is the feature.
        Accepting the future is a hole.

        Naive input is read as UTC and made explicit; aware input is converted to UTC.
        Everything downstream is aware, like `_now()` - MongoDB is what strips the offset,
        on write, and the read path puts it back. `FUTURE_SKEW` is the allowance for a
        client clock that runs slightly fast, not a window for choosing a date.
        """
        if v is None:
            return None
        v = v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
        if v > _now() + FUTURE_SKEW:
            raise ValueError(
                f"timestamp is more than {int(FUTURE_SKEW.total_seconds())}s in the future"
            )
        return v

    @field_validator("event_type")
    @classmethod
    def _normalise_type(cls, v: str) -> str:
        """`event_type` is a keyword in Elasticsearch and an index prefix in MongoDB.

        Normalising at the edge keeps "PageView" and "pageview" from becoming two
        separate groups in aggregations. Normalising on write is cheaper than
        normalising on every read.
        """
        v = v.strip().lower()
        if not v:
            raise ValueError("event_type must not be empty")
        return v


class Event(BaseModel):
    """The event as it travels internally: through the queue and into the stores."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    user_id: str
    source_url: str
    # When it HAPPENED. Never recomputed: this is what makes write order irrelevant to
    # the final state, and therefore what makes N concurrent workers safe.
    # See ARCHITECTURE.md §5.
    timestamp: datetime
    # When we ACCEPTED it. With `timestamp` it gives the client's clock skew; with the
    # write time, the pipeline's lag.
    received_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_input(cls, data: EventIn) -> Event:
        """Stamp the event at the HTTP edge. Called ONCE per request.

        The two server-generated fields (`event_id` and, when absent, `timestamp`) are
        assigned here and never touched again. Falling back to `now()` for the timestamp
        is safe *because it happens in the API*: it is fixed before the queue, so every
        redelivery shares the same value. The same `now()` inside the worker would break
        commutativity, because it would depend on which task won the race.
        """
        now = _now()
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=data.event_type,
            user_id=data.user_id,
            source_url=str(data.source_url),
            timestamp=data.timestamp or now,
            received_at=now,
            metadata=data.metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """The MongoDB document. `_id` is the `event_id`, so the upsert is idempotent
        without needing a separate unique index."""
        doc = self.model_dump()
        doc["_id"] = doc.pop("event_id")
        return doc


class EventAccepted(BaseModel):
    """The response to POST /events.

    Returns 202, not 201: when we answer, the event is in the queue, not in MongoDB.
    A 201 would claim a resource that does not exist yet.
    """

    event_id: str
    status: str = "accepted"
