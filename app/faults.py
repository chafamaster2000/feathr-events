"""Deliberate failure injection, for demonstrating what §6 of ARCHITECTURE.md claims.

The failure modes are the least verifiable part of the design. Nothing in the system will
break itself, so a reader has to break something — and the interesting claims are about
what *keeps working* while it is broken, which is exactly what nobody sees unless they try.

Two rules shape this module.

**It is not an endpoint into the harness.** `scripts/` reads logs and documents without
authentication, which is safe only because it runs on a developer's machine. Exposing that
over HTTP would turn it into an open admin API, and CLAUDE.md's fifth invariant says so.
This is the opposite direction: nothing is read, one flag is set, and the flag only makes
the application fail the way it would fail anyway.

**It cannot exist in production.** The route that reaches this is registered only when
`DEMO_MODE` is on — absent, not disabled behind a check. And `guard` short-circuits on the
same setting, so with the flag off this is a module that holds an empty set nobody writes.

What it does NOT simulate, and the console says so too: a network partition, a slow
dependency, a timeout, or a partial failure. It raises at the client boundary, which is
the shape of "the dependency refused", not the shape of "the dependency went quiet".
"""

from __future__ import annotations

from app.config import settings

DEPENDENCIES = ("mongodb", "elasticsearch", "redis")

_faulted: set[str] = set()


class InjectedFault(RuntimeError):
    """Raised where a real driver error would be raised, and handled by the same paths."""


def enable(dependency: str) -> None:
    _faulted.add(dependency)


def disable(dependency: str) -> None:
    _faulted.discard(dependency)


def clear() -> None:
    _faulted.clear()


def active() -> list[str]:
    return sorted(_faulted)


def is_faulted(dependency: str) -> bool:
    return settings.demo_mode and dependency in _faulted


def guard(dependency: str) -> None:
    """Fail here if this dependency is being simulated as down.

    Called from the adapters rather than the drivers, so the error surfaces exactly where
    a driver error would: inside the worker's write, inside the cache read. The code that
    handles it is the code that handles the real thing, which is the only reason this
    demonstrates anything.
    """
    if is_faulted(dependency):
        raise InjectedFault(f"{dependency} is being simulated as unavailable")
