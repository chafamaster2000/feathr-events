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
    # A millisecond of slack below, because the stamp is truncated to that resolution and
    # can therefore land just before a microsecond-precision reading taken first.
    assert before - timedelta(milliseconds=1) <= event.timestamp <= datetime.now(UTC)
    assert event.timestamp == event.received_at


def test_the_stamp_is_truncated_to_milliseconds() -> None:
    """So that one instant does not come back as two values.

    BSON stores milliseconds and Elasticsearch stores what it was given, so a microsecond
    stamp made the same event read `…173000` from MongoDB and `…173930Z` from search.
    Truncating where the value is created removes the discrepancy at its source.
    """
    assert Event.from_input(EventIn(**payload())).timestamp.microsecond % 1000 == 0


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


def test_the_multi_process_guard_catches_both_spellings_of_the_flag() -> None:
    """`--workers=2` and `--workers 2` are one instruction to click, which uvicorn uses.

    Only the space-separated form was caught, so the ordinary way of writing the flag
    walked past the guard for what `main.py` itself calls "the worst kind of bug". Two
    decisions rest on this function — the queue and the rate limiter both stay in process
    because it forbids the configuration that would break them — so a hole in it was
    holding up more than itself.
    """
    import sys

    from app.main import _refuse_multiple_processes

    original = sys.argv
    refused, allowed = [], []
    try:
        for argv in (
            ["uvicorn", "app.main:app", "--workers=2"],
            ["uvicorn", "-w=4"],
            ["uvicorn", "--workers", "2"],
            ["uvicorn", "-w", "8"],
            ["uvicorn", "--workers=1"],
            ["uvicorn", "app.main:app"],
        ):
            sys.argv = argv
            try:
                _refuse_multiple_processes()
                allowed.append(argv[-1])
            except RuntimeError:
                refused.append(argv[-1])
    finally:
        sys.argv = original

    assert refused == ["--workers=2", "-w=4", "2", "8"]
    assert allowed == ["--workers=1", "app.main:app"]
