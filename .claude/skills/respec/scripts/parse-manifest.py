#!/usr/bin/env python3
"""parse-manifest — deterministic dependency/manifest extraction for the Recon pass.

Usage:
    parse-manifest.py <root>

Detects and parses package manifests across ecosystems (Node, Go, Rust, Python,
PHP) and Unity (Packages/manifest.json + ProjectSettings/ProjectVersion.txt).
Emits Markdown. No third-party deps — TOML/JSON via stdlib, others line-based.
"""
from __future__ import annotations

import json
import os
import re
import sys

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def section(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    body = "\n".join(f"- {r}" for r in rows)
    return f"## {title}\n\n{body}\n"


def parse_package_json(path: str) -> str:
    raw = read(path)
    if raw is None:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"## package.json\n\n_parse error: {e}_\n"
    out = [f"## package.json (`{os.path.basename(path)}`)\n"]
    if data.get("name"):
        out.append(f"**name**: {data['name']}  ")
    if data.get("version"):
        out.append(f"**version**: {data['version']}  ")
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(key) or {}
        rows = [f"`{n}` {v}" for n, v in deps.items()]
        out.append("\n" + section(key, rows))
    scripts = data.get("scripts") or {}
    if scripts:
        out.append(section("scripts", [f"`{n}`: `{v}`" for n, v in scripts.items()]))
    return "\n".join(out)


def parse_go_mod(path: str) -> str:
    raw = read(path)
    if raw is None:
        return ""
    mod = re.search(r"^module\s+(\S+)", raw, re.M)
    gover = re.search(r"^go\s+(\S+)", raw, re.M)
    reqs = re.findall(r"^\s*([\w./-]+)\s+(v\S+)", raw, re.M)
    out = [f"## go.mod (`{os.path.basename(path)}`)\n"]
    if mod:
        out.append(f"**module**: {mod.group(1)}  ")
    if gover:
        out.append(f"**go**: {gover.group(1)}  ")
    out.append("\n" + section("require", [f"`{n}` {v}" for n, v in reqs]))
    return "\n".join(out)


def parse_cargo(path: str) -> str:
    raw = read(path)
    if raw is None:
        return ""
    out = [f"## Cargo.toml (`{os.path.basename(path)}`)\n"]
    if tomllib:
        try:
            data = tomllib.loads(raw)
            pkg = data.get("package", {})
            if pkg.get("name"):
                out.append(f"**name**: {pkg['name']}  ")
            if pkg.get("version"):
                out.append(f"**version**: {pkg['version']}  ")
            deps = data.get("dependencies", {})
            rows = [f"`{n}` {v if isinstance(v, str) else json.dumps(v)}" for n, v in deps.items()]
            out.append("\n" + section("dependencies", rows))
            return "\n".join(out)
        except Exception:  # noqa: BLE001 — fall through to line parse
            pass
    deps = re.findall(r"^\s*([\w-]+)\s*=\s*(.+)$", raw, re.M)
    out.append("\n" + section("dependencies (best-effort)", [f"`{n}` {v}" for n, v in deps]))
    return "\n".join(out)


def parse_pyproject(path: str) -> str:
    raw = read(path)
    if raw is None:
        return ""
    out = [f"## pyproject.toml (`{os.path.basename(path)}`)\n"]
    if tomllib:
        try:
            data = tomllib.loads(raw)
            proj = data.get("project", {})
            if proj.get("name"):
                out.append(f"**name**: {proj['name']}  ")
            if proj.get("version"):
                out.append(f"**version**: {proj['version']}  ")
            deps = proj.get("dependencies", []) or []
            out.append("\n" + section("dependencies", [f"`{d}`" for d in deps]))
            return "\n".join(out)
        except Exception:  # noqa: BLE001
            pass
    out.append("\n_(tomllib unavailable — inspect manually)_\n")
    return "\n".join(out)


def parse_composer(path: str) -> str:
    raw = read(path)
    if raw is None:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    out = [f"## composer.json (`{os.path.basename(path)}`)\n"]
    for key in ("require", "require-dev"):
        deps = data.get(key) or {}
        out.append("\n" + section(key, [f"`{n}` {v}" for n, v in deps.items()]))
    return "\n".join(out)


def parse_unity(root: str) -> str:
    out: list[str] = []
    ver = read(os.path.join(root, "ProjectSettings", "ProjectVersion.txt"))
    if ver:
        m = re.search(r"m_EditorVersion:\s*(\S+)", ver)
        if m:
            out.append(f"## Unity\n\n**Editor version**: {m.group(1)}\n")
    manifest = os.path.join(root, "Packages", "manifest.json")
    raw = read(manifest)
    if raw:
        try:
            data = json.loads(raw)
            deps = data.get("dependencies") or {}
            out.append(section("Packages/manifest.json", [f"`{n}` {v}" for n, v in deps.items()]))
        except json.JSONDecodeError:
            pass
    return "\n".join(out)


# (filename, parser) — checked at the Target root.
ROOT_MANIFESTS = [
    ("package.json", parse_package_json),
    ("go.mod", parse_go_mod),
    ("Cargo.toml", parse_cargo),
    ("pyproject.toml", parse_pyproject),
    ("composer.json", parse_composer),
]


def main() -> int:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        print("Usage: parse-manifest.py <root>", file=sys.stderr)
        return 1
    root = os.path.abspath(sys.argv[1])
    print("# Dependencies\n")
    found = False
    for name, parser in ROOT_MANIFESTS:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            chunk = parser(path)
            if chunk.strip():
                print(chunk)
                found = True
    unity = parse_unity(root)
    if unity.strip():
        print(unity)
        found = True
    if not found:
        print("_No recognized manifest at the Target root._")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
