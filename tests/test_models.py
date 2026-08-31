"""The event as it enters the system.

`models.py` is where the client's input stops being the client's. Two of the three
server-side decisions it makes are covered elsewhere by their consequences — the
`event_id` by the idempotency tests, the `event_type` normalisation by the aggregation
grouping. What was not covered is the field a client is allowed to set: `timestamp`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import FUTURE_SKEW, MAX_METADATA_BYTES, Event, EventIn


def payload(**over: object) -> dict:
    return {
        "event_type": "pageview",
        "user_id": "u-1",
        "source_url": "https://shop.example.com/p/1",
        **over,
    }


def test_a_client_may_back_date_an_event() -> None:
    """Late arrival is the normal case, not an error.

    A buffered or offline producer sends when it reconnects. The whole pipeline is built
    so that a late write still lands where the event belongs, which is only meaningful if
    the old timestamp survives validation.
    """
    old = datetime(1999, 1, 1, tzinfo=UTC)
    assert EventIn(**payload(timestamp=old)).timestamp == old


def test_a_client_may_not_forward_date_an_event() -> None:
    """The asymmetry is the point.

    Sorted descending, one event dated years ahead sits at the top of every listing until
    somebody removes it by hand, and opens a bucket that wide in every aggregation. It is
    not a typo, it is a lever — and the concurrency argument rests on this field, so a
    caller who can move it can move where any event lands.
    """
    with pytest.raises(ValidationError, match="in the future"):
        EventIn(**payload(timestamp=datetime(2031, 5, 5, tzinfo=UTC)))


def test_a_slightly_fast_client_clock_is_tolerated() -> None:
    """Unsynchronised machines are ordinary; refusing them would refuse real events."""
    near = datetime.now(UTC) + FUTURE_SKEW / 2
    assert EventIn(**payload(timestamp=near)).timestamp == near


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """Naive input is not rejected, it is made explicit.

    Left naive it would compare against an aware `now()` and raise a TypeError from deep
    inside validation — a 500 for a well-formed request.
    """
    naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    parsed = EventIn(**payload(timestamp=naive)).timestamp
    assert parsed is not None and parsed.tzinfo is UTC


def test_an_absent_timestamp_is_stamped_once_at_the_edge() -> None:
    """Stamped here so every redelivery of the same message shares the value.

    The same `now()` inside the worker would tie the result to which task won the race.
    """
    before = datetime.now(UTC)
    event = Event.from_input(EventIn(**payload()))
    assert before <= event.timestamp <= datetime.now(UTC)
    assert event.timestamp == event.received_at


def test_metadata_is_bounded() -> None:
    """Free-form is not the same as unbounded.

    The queue's own bound counts messages, so without this the 429 never fires on volume
    that matters: ten thousand events carrying megabytes each is tens of gigabytes of
    process memory. MongoDB would refuse the document at 16MB, which turns an oversized
    event into a deterministic poison message - five guaranteed failures and a worker slot
    each time, before it reaches the dead-letter.
    """
    with pytest.raises(ValidationError, match="over the"):
        EventIn(**payload(metadata={"blob": "x" * (MAX_METADATA_BYTES + 1)}))


def test_ordinary_metadata_passes() -> None:
    """The cap must not be in the way of what the brief describes: browser info, device
    type, feature-specific data."""
    ordinary = {"browser": "firefox", "device": "mobile", "plan": "pro", "amount": 42}
    assert EventIn(**payload(metadata=ordinary)).metadata == ordinary
