"""Structured NDJSON logging with a correlation id.

Adapted from the dev-workflow FastAPI reference snippet. Deviations from it, and why:

  * Lives at `app/observability.py` rather than `infrastructure/logging/` — this project
    has a flat `app/` package, and inventing a directory tree for one module would be
    worse than following the reference layout literally.
  * Logs the domain's own `event_id` into `ctx` alongside the transport-level task id.
    This system already has a correlation id that survives every hop (API -> queue ->
    worker -> both stores); the header id only covers one request. Both are recorded so a
    trace can be followed either way.
  * WebSocket handling is kept even though this app has none: it costs three lines and
    removing it would silently break the contract if a WS route is ever added.

One NDJSON line per event, written to `.logs/agent/<YYYY-MM-DD>/<task-id>.log`:

    {"ts", "level", "scope", "taskId", "msg", "ctx"}

Pure ASGI middleware, not `BaseHTTPMiddleware`, so it covers both scopes without
breaking streaming responses. Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import traceback
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

LOG_ROOT = Path.cwd() / ".logs" / "agent"
REDACTED_HEADERS = {"authorization", "cookie", "x-api-key"}

# A generated per-request id is not a task: it identifies one request, and giving each
# one its own file means one open file handle per request, held forever. That is a file
# descriptor leak, and it is not theoretical - it exhausted the container's 1024 handle
# limit after roughly a thousand requests, at which point the process could no longer
# accept connections at all. Every 502 and dropped connection chased during development
# traced back to here. Generated ids share one sink; only an explicit x-agent-task-id
# earns a file of its own, which is the entire point of naming a task.
SHARED_SINK = "requests"
GENERATED_PREFIX = "req-"
# And even named sinks are bounded, so a caller sending a fresh header per request cannot
# reproduce the leak from outside.
MAX_SINKS = 32

_task_id: ContextVar[str] = ContextVar("agent_task_id", default="")
_loggers: OrderedDict[str, logging.Logger | None] = OrderedDict()


class NdjsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "scope": getattr(record, "scope", record.name),
            "taskId": getattr(record, "task_id", "") or _task_id.get() or "untracked",
            "msg": record.getMessage(),
        }
        if ctx := getattr(record, "ctx", None):
            line["ctx"] = ctx
        return json.dumps(line, ensure_ascii=False, default=str)


def _logger_for(task_id: str) -> logging.Logger | None:
    """Build (once) the NDJSON logger for a task id, or None if the sink is unusable.

    Returning None rather than raising is the whole point. Observability must never be
    able to take the application down: a read-only mount, a full disk or a uid mismatch
    on a bind mount are all environment problems, and none of them are a reason to fail
    a request that was otherwise going to succeed. Same principle as the cache in
    `app/cache.py`, and it is not hypothetical - a permission error on the mounted
    .logs volume turned every response into a 500 the first time this was wired.
    """
    sink = SHARED_SINK if task_id.startswith(GENERATED_PREFIX) else task_id
    if sink in _loggers:
        _loggers.move_to_end(sink)
        return _loggers[sink]

    # Close the least recently used sink rather than letting the map grow.
    while len(_loggers) >= MAX_SINKS:
        _, evicted = _loggers.popitem(last=False)
        if evicted is not None:
            for handler in evicted.handlers[:]:
                handler.close()
                evicted.removeHandler(handler)
    try:
        day_dir = LOG_ROOT / datetime.now(UTC).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        # The day directory is created by whichever process writes first. On the bind
        # mount used in development that can be the host (pytest, scripts/seed.py) or
        # the container, and they run as different uids - so whoever loses the race is
        # locked out of a directory it can see. Widening the mode keeps both writing.
        # Development-only: `.logs/` is gitignored and never enters the image.
        with contextlib.suppress(OSError):
            day_dir.chmod(0o777)
        handler = RotatingFileHandler(
            day_dir / f"{sink}.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
    except OSError:
        # Warn once per task id through the ordinary console logger, then stay quiet.
        logging.getLogger(__name__).warning(
            "agent log sink unavailable at %s; structured logging disabled", LOG_ROOT
        )
        _loggers[sink] = None
        return None
    handler.setFormatter(NdjsonFormatter())
    logger = logging.getLogger(f"agent.{sink}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # keep NDJSON out of uvicorn's console handler
    logger.addHandler(handler)
    _loggers[sink] = logger
    return logger


def log(
    scope: str,
    msg: str,
    ctx: dict[str, Any] | None = None,
    level: int = logging.INFO,
    task_id: str | None = None,
) -> None:
    """Emit one NDJSON event from any layer.

    The task id is picked up from the request context, so a worker writing about an
    event does not need to be handed the id explicitly.
    """
    tid = task_id or _task_id.get() or "untracked"
    if (logger := _logger_for(tid)) is not None:
        logger.log(level, msg, extra={"scope": scope, "ctx": ctx, "task_id": tid})


def _redact(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("[REDACTED]" if k in REDACTED_HEADERS else v) for k, v in headers.items()}


def _resolve_task_id(scope: dict[str, Any], headers: dict[str, str]) -> str:
    if tid := headers.get("x-agent-task-id"):
        return tid
    query = parse_qs(scope.get("query_string", b"").decode())
    if tid_values := query.get("agent_task_id"):
        return tid_values[0]
    return f"req-{uuid.uuid4().hex[:8]}"


class AgentLoggerMiddleware:
    """Wired in `main.py` with `app.add_middleware(AgentLoggerMiddleware)`."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        task_id = _resolve_task_id(scope, headers)
        token = _task_id.set(task_id)
        kind = "ws" if scope["type"] == "websocket" else "http"
        method = scope.get("method", "WS")
        path = scope.get("path", "")
        start = time.perf_counter()
        status: dict[str, int] = {}

        log(
            f"{kind}.request",
            f"{method} {path}",
            ctx={"headers": _redact(headers), "query": scope.get("query_string", b"").decode()},
        )

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            log(
                f"{kind}.response",
                f"{method} {path} -> {status.get('code', 'closed')}",
                ctx={
                    "durationMs": round((time.perf_counter() - start) * 1000),
                    "status": status.get("code"),
                },
            )
        except Exception as err:
            log(
                f"{kind}.error",
                f"{method} {path} -> {type(err).__name__}",
                level=logging.ERROR,
                ctx={
                    "durationMs": round((time.perf_counter() - start) * 1000),
                    "error": str(err),
                    "stack": traceback.format_exc(limit=8),
                },
            )
            raise
        finally:
            _task_id.reset(token)
