#!/usr/bin/env python3
"""file-tree — deterministic directory tree with sizes for the Recon evidence pass.

Usage:
    file-tree.py <root> [--depth N] [--max-entries N]

Prints a Markdown tree of the Target, skipping noise (VCS, deps, build output,
Unity Library/Temp). The agent reasons over this instead of walking the repo by hand.
"""
from __future__ import annotations

import argparse
import os
import sys

# Directories that never carry audit signal — skip wholesale.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "out", "target", ".next", ".turbo", ".cache",
    # Unity-generated, regenerated from Assets/ + ProjectSettings/ — pure noise.
    "Library", "Temp", "Obj", "obj", "Logs", "UserSettings", "MemoryCaptures",
    "Build", "Builds", ".vs", ".idea", ".gradle",
}


def fmt_size(n: int) -> str:
    units = ["B", "K", "M", "G", "T"]
    f = float(n)
    for u in units:
        if f < 1024 or u == "T":
            return f"{f:.0f}{u}" if u == "B" else f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}T"


def walk(root: str, max_depth: int, max_entries: int) -> list[str]:
    lines: list[str] = []
    root = os.path.abspath(root)

    def recurse(path: str, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                os.scandir(path),
                key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()),
            )
        except (PermissionError, FileNotFoundError):
            return
        entries = [e for e in entries if not (e.is_dir(follow_symlinks=False) and e.name in SKIP_DIRS)]
        truncated = False
        if len(entries) > max_entries:
            entries, truncated = entries[:max_entries], True
        for i, entry in enumerate(entries):
            last = i == len(entries) - 1 and not truncated
            connector = "└── " if last else "├── "
            if entry.is_dir(follow_symlinks=False):
                lines.append(f"{prefix}{connector}{entry.name}/")
                recurse(entry.path, prefix + ("    " if last else "│   "), depth + 1)
            else:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                lines.append(f"{prefix}{connector}{entry.name}  ({fmt_size(size)})")
        if truncated:
            lines.append(f"{prefix}└── … ({len(os.listdir(path)) - max_entries} more)")

    lines.append(f"{os.path.basename(root) or root}/")
    recurse(root, "", 1)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--max-entries", type=int, default=200)
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"Error: not a directory: {args.root}", file=sys.stderr)
        return 1

    print("# File tree\n")
    print("```")
    print("\n".join(walk(args.root, args.depth, args.max_entries)))
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
