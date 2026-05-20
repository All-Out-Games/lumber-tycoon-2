#!/usr/bin/env python3
"""Remove Sprite_Renderer components from tree .e scene files.

By default this is a dry run. Pass --apply to write changes.

Examples:
  python tools/remove_tree_sprite_renderers.py
  python tools/remove_tree_sprite_renderers.py --apply
  python tools/remove_tree_sprite_renderers.py --scene-dir scene --name-filter tree --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


SPRITE_RENDERER = "sprite_renderer"


def split_top_level_objects(text: str) -> tuple[list[str], str]:
    """Split an .e file into 3 header lines plus top-level JSON-ish blocks.

    .e files in this project look like:
      line 1: format/version
      line 2: id
      line 3: id
      { entity json },
      { component json },
      { component json }

    This parser keeps each top-level {...} block without its separating comma.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) < 4:
        return lines, ""

    header = lines[:3]
    body = "".join(lines[3:])
    return header, body


def iter_object_blocks(body: str) -> Iterable[str]:
    depth = 0
    in_string = False
    escape = False
    start = None

    for i, ch in enumerate(body):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                yield body[start : i + 1]
                start = None

    if depth != 0:
        raise ValueError("unbalanced braces")


def is_sprite_renderer_block(block: str) -> bool:
    try:
        obj = json.loads(block)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON block: {exc}") from exc

    component_type = str(obj.get("component_type", "")).lower()
    internal_type = str(obj.get("internal_component_type", "")).lower()
    return component_type == SPRITE_RENDERER or internal_type == SPRITE_RENDERER


def rewrite_e_file(path: Path) -> tuple[int, str | None]:
    original = path.read_text(encoding="utf-8")
    header, body = split_top_level_objects(original)
    if not body:
        return 0, None

    blocks = list(iter_object_blocks(body))
    kept: list[str] = []
    removed = 0

    for block in blocks:
        if is_sprite_renderer_block(block):
            removed += 1
        else:
            kept.append(block)

    if removed == 0:
        return 0, None

    newline = "\r\n" if "\r\n" in original else "\n"
    rewritten = "".join(header) + ("," + newline).join(kept) + newline
    return removed, rewritten


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove Sprite_Renderer components from tree .e files. Dry-run by default."
    )
    parser.add_argument(
        "--scene-dir",
        default="scene",
        help="Directory containing .e files, relative to the current working directory unless absolute.",
    )
    parser.add_argument(
        "--name-filter",
        default="tree",
        help="Case-insensitive substring used to select .e files by filename. Default: tree",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this flag, only reports what would change.",
    )
    args = parser.parse_args()

    scene_dir = Path(args.scene_dir)
    if not scene_dir.exists():
        raise SystemExit(f"Scene directory not found: {scene_dir}")

    needle = args.name_filter.lower()
    files = [p for p in scene_dir.rglob("*.e") if needle in p.name.lower()]

    changed_files = 0
    removed_components = 0
    errors: list[str] = []

    for path in files:
        try:
            removed, rewritten = rewrite_e_file(path)
        except Exception as exc:  # keep scanning and report all problem files
            errors.append(f"{path}: {exc}")
            continue

        if removed == 0:
            continue

        changed_files += 1
        removed_components += removed
        if args.apply and rewritten is not None:
            path.write_text(rewritten, encoding="utf-8", newline="")

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: scanned {len(files)} tree .e files")
    print(f"{mode}: {'removed' if args.apply else 'would remove'} {removed_components} Sprite_Renderer components from {changed_files} files")

    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[:20]:
            print(f"  {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        return 1

    if not args.apply:
        print("Run with --apply to write the changes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
