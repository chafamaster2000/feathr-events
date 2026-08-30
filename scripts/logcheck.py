#!/usr/bin/env python3
"""Development log harness: unifies the stack's four log formats into one stream.

Each container logs differently, and none of them agree:

    mongo          JSON            level in "s": F E W I D
    elasticsearch  JSON (ECS)      level in "log.level": WARN, ERROR, ...
    redis          plain text      level in ONE character: # warn, * notice, - verbose, . debug
    api            two formats     uvicorn ("INFO:  ...") + Python logging

Reviewing them by hand means reading four dialects and correlating timestamps with
different precision. This normalises them into a single record:

    {"ts", "service", "level", "msg", "src", "raw"}

Typical use -- after an integration run, asking "did anything complain?":

    python3 scripts/logcheck.py                      # WARN+ from the last 10m
    python3 scripts/logcheck.py --since 2m --level INFO
    python3 scripts/logcheck.py --service mongo,api --level ERROR
    python3 scripts/logcheck.py --json               # NDJSON into .logs/agent/

No dependencies: stdlib only, runs on any python3.

Development only. It is excluded from the Docker image -- see ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SERVICES = ["mongo", "elasticsearch", "redis", "api"]

# Severity order. UNKNOWN sits above WARN on purpose: a line that could not be parsed
# cannot be declared harmless, and Python tracebacks land exactly there.
LEVELS = ["DEBUG", "INFO", "UNKNOWN", "WARN", "ERROR", "FATAL"]
RANK = {name: i for i, name in enumerate(LEVELS)}

MONGO_SEVERITY = {"F": "FATAL", "E": "ERROR", "W": "WARN", "I": "INFO", "D": "DEBUG"}
# Redis encodes the level in a single character (see server.c: LL_DEBUG..LL_WARNING).
REDIS_SEVERITY = {"#": "WARN", "*": "INFO", "-": "DEBUG", ".": "DEBUG"}

RE_REDIS = re.compile(
    r"^\d+:\w+\s+(?P<ts>\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<lvl>[.\-*#])\s+(?P<msg>.*)$"
)
RE_API_LOGGING = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+(?P<lvl>[A-Z]+)\s+"
    r"(?P<src>\S+)\s+::\s+(?P<msg>.*)$"
)
RE_API_UVICORN = re.compile(r"^(?P<lvl>DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(?P<msg>.*)$")

NORMALIZE = {"WARNING": "WARN", "CRITICAL": "FATAL", "TRACE": "DEBUG", "SEVERE": "ERROR"}


def norm_level(raw: str) -> str:
    lvl = NORMALIZE.get(raw.strip().upper(), raw.strip().upper())
    return lvl if lvl in RANK else "UNKNOWN"


def iso(ts: str) -> str:
    """The four services use different date formats. Normalise to ISO-8601 UTC."""
    for fmt in ("%d %b %Y %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S,%f"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            pass
    return ts  # mongo and ES already emit ISO


def parse_mongo(line: str) -> dict | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    return {
        "ts": d.get("t", {}).get("$date", ""),
        "level": MONGO_SEVERITY.get(str(d.get("s", "")).strip(), "UNKNOWN"),
        "msg": d.get("msg", ""),
        "src": d.get("c", ""),
    }


def parse_elasticsearch(line: str) -> dict | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    return {
        "ts": d.get("@timestamp", ""),
        "level": norm_level(str(d.get("log.level", ""))),
        "msg": d.get("message", ""),
        "src": d.get("service.name", ""),
    }


def parse_redis(line: str) -> dict | None:
    m = RE_REDIS.match(line)
    if not m:
        return None
    return {
        "ts": iso(m["ts"]),
        "level": REDIS_SEVERITY.get(m["lvl"], "UNKNOWN"),
        "msg": m["msg"],
        "src": "redis",
    }


def parse_api(line: str) -> dict | None:
    if m := RE_API_LOGGING.match(line):
        return {"ts": iso(m["ts"]), "level": norm_level(m["lvl"]), "msg": m["msg"], "src": m["src"]}
    if m := RE_API_UVICORN.match(line):
        return {"ts": "", "level": norm_level(m["lvl"]), "msg": m["msg"], "src": "uvicorn"}
    return None


PARSERS = {
    "mongo": parse_mongo,
    "elasticsearch": parse_elasticsearch,
    "redis": parse_redis,
    "api": parse_api,
}


def collect(service: str, since: str) -> list[dict]:
    cmd = ["docker", "compose", "logs", "--no-log-prefix", "--no-color", "--since", since, service]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! {service}: could not read the logs ({e})", file=sys.stderr)
        return []
    if out.returncode != 0:
        print(
            f"  ! {service}: docker compose logs failed - {out.stderr.strip()[:120]}",
            file=sys.stderr,
        )
        return []

    parse = PARSERS[service]
    records = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        rec = parse(line)
        if rec is None:
            # Did not parse: a traceback, a startup banner, or an unexpected format.
            # Marked UNKNOWN rather than dropped -- discarding what you do not understand
            # is how the errors that matter get lost.
            rec = {"ts": "", "level": "UNKNOWN", "msg": line.strip(), "src": "?"}
        rec["service"] = service
        rec["raw"] = line
        records.append(rec)
    return records


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--since", default="10m", help="time window (e.g. 5m, 1h, or a timestamp). default: 10m"
    )
    ap.add_argument(
        "--level", default="WARN", choices=LEVELS, help="minimum level to show. default: WARN"
    )
    ap.add_argument("--service", default=",".join(SERVICES), help="services, comma separated")
    ap.add_argument(
        "--json", action="store_true", help="emit NDJSON and save it under .logs/agent/"
    )
    ap.add_argument("--limit", type=int, default=60, help="maximum lines to print. default: 60")
    args = ap.parse_args()

    wanted = [s.strip() for s in args.service.split(",") if s.strip() in SERVICES]
    if not wanted:
        print(f"valid services: {', '.join(SERVICES)}", file=sys.stderr)
        return 2

    all_records: list[dict] = []
    for svc in wanted:
        all_records.extend(collect(svc, args.since))

    threshold = RANK[args.level]
    hits = [r for r in all_records if RANK.get(r["level"], 2) >= threshold]
    hits.sort(key=lambda r: (r["ts"] or "", r["service"]))

    if args.json:
        out_dir = Path(".logs/agent")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"stack-{stamp}.ndjson"
        with path.open("w", encoding="utf-8") as fh:
            for r in hits:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        for r in hits:
            print(json.dumps(r, ensure_ascii=False))
        print(f"\n-> {len(hits)} records in {path}", file=sys.stderr)
        return 1 if any(RANK.get(r["level"], 2) >= RANK["ERROR"] for r in hits) else 0

    # ---- summary by service and level ----
    print(f"\nwindow: last {args.since}   threshold: {args.level}+\n")
    header = f"{'service':<16}" + "".join(f"{lv:>9}" for lv in LEVELS) + f"{'total':>9}"
    print(header)
    print("-" * len(header))
    for svc in wanted:
        rows = [r for r in all_records if r["service"] == svc]
        counts = [sum(1 for r in rows if r["level"] == lv) for lv in LEVELS]
        print(f"{svc:<16}" + "".join(f"{c:>9}" for c in counts) + f"{len(rows):>9}")

    if not hits:
        print(f"\n  Nothing complained above {args.level}. The stack is clean.\n")
        return 0

    print(f"\n---- {len(hits)} en {args.level}+ " + "-" * 46)
    for r in hits[: args.limit]:
        ts = (r["ts"] or "")[11:23].ljust(12)
        src = (r["src"] or "")[:18]
        msg = r["msg"].replace("\n", " ")[:110]
        print(f"{ts} {r['service']:<14} {r['level']:<8} {src:<19} {msg}")
    if len(hits) > args.limit:
        print(f"... and {len(hits) - args.limit} more (raise --limit)")
    print()
    return 1 if any(RANK.get(r["level"], 2) >= RANK["ERROR"] for r in hits) else 0


if __name__ == "__main__":
    sys.exit(main())
