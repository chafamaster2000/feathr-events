#!/usr/bin/env python3
"""unity-scene-dump — deterministic GameObject hierarchy + component dump for Unity Targets.

Usage:
    unity-scene-dump.py <project-root> [--limit N]

Unity .unity / .prefab files are YAML with custom `--- !u!<class> &<fileID>` tags
that break standard YAML parsers, so this is a line-based extractor. It:
  1. builds a guid -> script-name map from *.cs.meta (to name MonoBehaviours),
  2. parses each scene/prefab into objects, links Transforms into a hierarchy,
  3. prints each GameObject tree with its attached component types,
  4. lists assembly definitions (.asmdef).

The agent reasons over this Markdown instead of reading raw Unity YAML.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

DOC_RE = re.compile(r"^--- !u!(\d+) &(\d+)")
GUID_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")
FILEID_RE = re.compile(r"fileID:\s*(-?\d+)")

# Common Unity class ids → readable names. Unknown ids fall back to Component(<id>).
CLASS_NAMES = {
    1: "GameObject", 4: "Transform", 224: "RectTransform", 114: "MonoBehaviour",
    20: "Camera", 108: "Light", 33: "MeshFilter", 23: "MeshRenderer",
    212: "SpriteRenderer", 137: "SkinnedMeshRenderer", 65: "BoxCollider",
    135: "SphereCollider", 136: "CapsuleCollider", 64: "MeshCollider",
    54: "Rigidbody", 50: "Rigidbody2D", 61: "BoxCollider2D", 58: "CircleCollider2D",
    68: "EdgeCollider2D", 95: "Animator", 111: "Animation", 82: "AudioSource",
    81: "AudioListener", 143: "CharacterController", 198: "ParticleSystem",
    223: "Canvas", 222: "CanvasRenderer", 225: "CanvasGroup", 1001: "PrefabInstance",
    120: "LineRenderer", 96: "TrailRenderer", 104: "RenderSettings",
}


def build_guid_map(root: str) -> dict[str, str]:
    """guid (from .cs.meta) -> script class name (the .cs basename)."""
    guid_to_script: dict[str, str] = {}
    assets = os.path.join(root, "Assets")
    base = assets if os.path.isdir(assets) else root
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("Library", "Temp", "obj", "Obj")]
        for fn in filenames:
            if fn.endswith(".cs.meta"):
                meta = os.path.join(dirpath, fn)
                try:
                    with open(meta, encoding="utf-8", errors="ignore") as f:
                        m = GUID_RE.search(f.read())
                except OSError:
                    continue
                if m:
                    guid_to_script[m.group(1)] = fn[: -len(".cs.meta")]
    return guid_to_script


class UObject:
    __slots__ = ("file_id", "class_id", "type_name", "name", "go_id",
                 "father_id", "children", "script_guid")

    def __init__(self, file_id: str, class_id: int) -> None:
        self.file_id = file_id
        self.class_id = class_id
        self.type_name: str | None = None
        self.name: str | None = None
        self.go_id: str | None = None       # m_GameObject this component belongs to
        self.father_id: str = "0"           # transform parent
        self.children: list[str] = []        # child transform fileIDs
        self.script_guid: str | None = None  # for MonoBehaviour


def parse_file(path: str) -> dict[str, UObject]:
    objs: dict[str, UObject] = {}
    cur: UObject | None = None
    in_children = False
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return objs

    for line in lines:
        header = DOC_RE.match(line)
        if header:
            cur = UObject(header.group(2), int(header.group(1)))
            objs[cur.file_id] = cur
            in_children = False
            continue
        if cur is None:
            continue
        stripped = line.strip()
        # first top-level key after the header names the object type, e.g. "GameObject:"
        if cur.type_name is None and re.match(r"^[A-Za-z]", line) and stripped.endswith(":"):
            cur.type_name = stripped[:-1]
            continue
        if stripped.startswith("m_Name:"):
            cur.name = stripped.split("m_Name:", 1)[1].strip()
        elif stripped.startswith("m_GameObject:"):
            fid = FILEID_RE.search(stripped)
            if fid:
                cur.go_id = fid.group(1)
        elif stripped.startswith("m_Father:"):
            fid = FILEID_RE.search(stripped)
            if fid:
                cur.father_id = fid.group(1)
        elif stripped.startswith("m_Script:"):
            g = GUID_RE.search(stripped)
            if g:
                cur.script_guid = g.group(1)
        elif stripped.startswith("m_Children:"):
            in_children = True
            continue
        elif in_children and stripped.startswith("- {"):
            fid = FILEID_RE.search(stripped)
            if fid and fid.group(1) != "0":
                cur.children.append(fid.group(1))
            continue
        if in_children and not stripped.startswith("- "):
            in_children = False
    return objs


def comp_label(o: UObject, guid_map: dict[str, str]) -> str:
    if o.class_id == 114 and o.script_guid:
        name = guid_map.get(o.script_guid)
        return name if name else f"MonoBehaviour(guid:{o.script_guid[:8]}…)"
    return CLASS_NAMES.get(o.class_id, f"Component({o.class_id})")


def dump_file(path: str, root: str, guid_map: dict[str, str]) -> str:
    objs = parse_file(path)
    if not objs:
        return ""
    gameobjects = {fid: o for fid, o in objs.items() if o.class_id == 1}
    transforms = {fid: o for fid, o in objs.items() if o.class_id in (4, 224)}

    # GameObject fileID -> its transform
    go_to_tr: dict[str, UObject] = {}
    for tr in transforms.values():
        if tr.go_id:
            go_to_tr[tr.go_id] = tr
    # transform fileID -> GameObject name
    tr_to_name: dict[str, str] = {}
    for go_id, tr in go_to_tr.items():
        go = gameobjects.get(go_id)
        tr_to_name[tr.file_id] = (go.name if go and go.name else "(unnamed)")

    # components grouped by GameObject
    comps_by_go: dict[str, list[str]] = {}
    for o in objs.values():
        if o.class_id in (1, 4, 224):
            continue
        if o.go_id and o.go_id in gameobjects:
            comps_by_go.setdefault(o.go_id, []).append(comp_label(o, guid_map))

    roots = [tr for tr in transforms.values() if tr.father_id == "0"]
    out: list[str] = []
    rel = os.path.relpath(path, root)
    kind = "Prefab" if path.endswith(".prefab") else "Scene"
    out.append(f"### {kind}: `{rel}`\n")
    out.append("```")

    def render(tr: UObject, depth: int) -> None:
        go_id = tr.go_id or ""
        name = tr_to_name.get(tr.file_id, "(unnamed)")
        comps = sorted(set(comps_by_go.get(go_id, [])))
        comp_str = f"  [{', '.join(comps)}]" if comps else ""
        out.append("  " * depth + f"- {name}{comp_str}")
        kids = [transforms[c] for c in tr.children if c in transforms]
        if not kids:  # fall back to father links if m_Children was absent
            kids = [t for t in transforms.values() if t.father_id == tr.file_id]
        for kid in sorted(kids, key=lambda t: tr_to_name.get(t.file_id, "")):
            render(kid, depth + 1)

    for r in sorted(roots, key=lambda t: tr_to_name.get(t.file_id, "")):
        render(r, 0)
    out.append("```")
    return "\n".join(out)


def list_asmdefs(root: str) -> str:
    rows: list[str] = []
    base = os.path.join(root, "Assets")
    base = base if os.path.isdir(base) else root
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("Library", "Temp", "obj", "Obj")]
        for fn in filenames:
            if fn.endswith(".asmdef"):
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                    refs = data.get("references", []) or []
                    rows.append(f"`{data.get('name', fn)}` (`{os.path.relpath(p, root)}`)"
                                + (f" → refs: {', '.join(refs)}" if refs else ""))
                except (OSError, json.JSONDecodeError):
                    rows.append(f"`{os.path.relpath(p, root)}` (unparsed)")
    if not rows:
        return ""
    return "## Assembly definitions\n\n" + "\n".join(f"- {r}" for r in rows) + "\n"


def find_targets(root: str, limit: int) -> list[str]:
    out: list[str] = []
    base = os.path.join(root, "Assets")
    base = base if os.path.isdir(base) else root
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("Library", "Temp", "obj", "Obj")]
        for fn in sorted(filenames):
            if fn.endswith(".unity") or fn.endswith(".prefab"):
                out.append(os.path.join(dirpath, fn))
    # scenes first, then prefabs; stable order
    out.sort(key=lambda p: (not p.endswith(".unity"), p.lower()))
    return out[:limit] if limit else out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=0, help="max scenes+prefabs (0 = all)")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Error: not a directory: {root}", file=sys.stderr)
        return 1

    guid_map = build_guid_map(root)
    targets = find_targets(root, args.limit)

    print("# Unity scene & prefab hierarchy\n")
    print(f"_Resolved {len(guid_map)} script GUIDs; {len(targets)} scenes/prefabs._\n")
    for p in targets:
        chunk = dump_file(p, root, guid_map)
        if chunk:
            print(chunk + "\n")
    asm = list_asmdefs(root)
    if asm:
        print(asm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
