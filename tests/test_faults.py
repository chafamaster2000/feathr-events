"""Deliberate failure injection, and the two things that must be true about it.

It exists because §6's failure modes are the least verifiable claims in the design:
nothing breaks itself, and what makes each claim interesting is what keeps working while
something is down. It is also the most dangerous thing in the repo if it ever leaks, so
both halves are tested.
"""

from __future__ import annotations

import pytest

from app import faults
from app.config import settings


@pytest.fixture(autouse=True)
def _clean() -> None:
    faults.clear()
    yield
    faults.clear()


def test_guard_is_inert_without_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route is absent in production, but the guard must not depend on that alone.

    Two independent gates: the endpoint is never registered, and the check short-circuits
    on the same setting. A flag set by any other means still cannot break a real system.
    """
    monkeypatch.setattr(settings, "demo_mode", False)
    faults.enable("mongodb")
    faults.guard("mongodb")  # must not raise


def test_guard_raises_where_a_driver_error_would(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point is that the real handling path runs.

    It raises inside the adapter, so the worker's failure path, the cache's swallow, and
    the health ping all react to it exactly as they react to the genuine article.
    """
    monkeypatch.setattr(settings, "demo_mode", True)
    faults.enable("redis")
    with pytest.raises(faults.InjectedFault, match="redis"):
        faults.guard("redis")
    faults.guard("mongodb")  # unrelated dependencies stay up


def test_a_fault_is_reversible_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    faults.enable("elasticsearch")
    assert faults.active() == ["elasticsearch"]
    faults.disable("elasticsearch")
    assert faults.active() == []
    faults.guard("elasticsearch")
