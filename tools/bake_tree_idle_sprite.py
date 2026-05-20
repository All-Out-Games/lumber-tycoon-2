#!/usr/bin/env python3
"""Bake the pine tree idle art to a PNG and apply it to Lumber_Tree Sprite_Renderers.

Default mode is a dry run. Pass --apply to write files.

This tool does two jobs:
  1. Uses a high-quality upright idle pine PNG at res/baked_tree.png.
  2. Ensures every scene .e with a Lumber_Tree has a Sprite_Renderer using that PNG.

Optional --restore-missing-from-git re-adds Sprite_Renderer component blocks removed from
-tree-named .e files by reading them from HEAD before converting Lumber_Tree sprites.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable, Any

DEFAULT_SOURCE = Path("res/baked_tree.png")
DEFAULT_OUTPUT = Path("res/baked_tree.png")
SPRITE_RENDERER = "Sprite_Renderer"
LUMBER_TREE = "Lumber_Tree"


def split_e_text(text: str) -> tuple[list[str], str]:
    lines = text.splitlines(keepends=True)
    if len(lines) < 4:
        return lines, ""
    return lines[:3], "".join(lines[3:])


def iter_object_blocks(body: str) -> Iterable[str]:
    depth = 0
    in_string = False
    escape = False
    start: int | None = None
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


def parse_e_file(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    header, body = split_e_text(text)
    blocks: list[dict[str, Any]] = []
    for block in iter_object_blocks(body):
        blocks.append(json.loads(block))
    return header, blocks


def render_e_file(header: list[str], blocks: list[dict[str, Any]], newline: str = "\n") -> str:
    return "".join(header) + ("," + newline).join(json.dumps(block, indent=2) for block in blocks) + newline


def internal_type(block: dict[str, Any]) -> str:
    return str(block.get("internal_component_type", block.get("component_type", "")))


def is_sprite_renderer(block: dict[str, Any]) -> bool:
    return internal_type(block).lower() == SPRITE_RENDERER.lower() or str(block.get("component_type", "")).lower() == SPRITE_RENDERER.lower()


def has_lumber_tree(blocks: list[dict[str, Any]]) -> bool:
    return any(internal_type(block) == LUMBER_TREE for block in blocks)


def max_scene_aoid(scene_dir: Path) -> int:
    max_aoid = 0
    for path in scene_dir.rglob("*.e"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r'"aoid"\s*:\s*(\d+)', text):
            max_aoid = max(max_aoid, int(match.group(1)))
    return max_aoid


def make_sprite_block(aoid: int, texture_path: str) -> dict[str, Any]:
    return {
        "cid": 97,
        "aoid": aoid,
        "component_type": "Internal_Component",
        "internal_component_type": SPRITE_RENDERER,
        "data": {
            "texture": texture_path,
            "tint": {"X": 1, "Y": 1, "Z": 1, "W": 1},
            "depth_offset": -0.274,
            "layer": 0,
            "scale": {"X": 1, "Y": 1},
        },
    }


def configure_lumber_sprite(block: dict[str, Any], texture_path: str) -> None:
    block["component_type"] = "Internal_Component"
    block["internal_component_type"] = SPRITE_RENDERER
    data = block.setdefault("data", {})
    data["texture"] = texture_path
    data["tint"] = {"X": 1, "Y": 1, "Z": 1, "W": 1}
    data["depth_offset"] = -0.274
    data["layer"] = 0
    data["scale"] = {"X": 1, "Y": 1}


def git_head_text(path: Path) -> str | None:
    repo_path = path.as_posix()
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{repo_path}"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    return result.stdout


def sprite_blocks_from_text(text: str) -> list[dict[str, Any]]:
    _header, body = split_e_text(text)
    blocks: list[dict[str, Any]] = []
    for raw in iter_object_blocks(body):
        block = json.loads(raw)
        if is_sprite_renderer(block):
            blocks.append(block)
    return blocks


def restore_missing_sprite_blocks_from_git(scene_dir: Path, files: list[Path], apply: bool) -> tuple[int, int]:
    restored_files = 0
    restored_blocks = 0
    for path in files:
        header, blocks = parse_e_file(path)
        if any(is_sprite_renderer(block) for block in blocks):
            continue
        head = git_head_text(path)
        if not head:
            continue
        old_sprites = sprite_blocks_from_text(head)
        if not old_sprites:
            continue
        restored_files += 1
        restored_blocks += len(old_sprites)
        if apply:
            blocks.extend(old_sprites)
            path.write_text(render_e_file(header, blocks), encoding="utf-8", newline="")
    return restored_files, restored_blocks


def bake_png(source: Path, output: Path, apply: bool) -> bool:
    if not source.exists():
        raise FileNotFoundError(f"source PNG not found: {source}")
    changed = not output.exists() or source.read_bytes() != output.read_bytes()
    if changed and apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes())
    return changed


def apply_lumber_tree_sprites(scene_dir: Path, texture_path: str, apply: bool) -> tuple[int, int, int]:
    files = sorted(scene_dir.rglob("*.e"))
    next_aoid = max_scene_aoid(scene_dir) + 1
    touched_files = 0
    updated_sprites = 0
    created_sprites = 0

    for path in files:
        header, blocks = parse_e_file(path)
        if not has_lumber_tree(blocks):
            continue

        sprite_blocks = [block for block in blocks if is_sprite_renderer(block)]
        if sprite_blocks:
            for block in sprite_blocks:
                configure_lumber_sprite(block, texture_path)
                updated_sprites += 1
        else:
            blocks.append(make_sprite_block(next_aoid, texture_path))
            next_aoid += 1
            created_sprites += 1

        touched_files += 1
        if apply:
            path.write_text(render_e_file(header, blocks), encoding="utf-8", newline="")

    return touched_files, updated_sprites, created_sprites


def main() -> int:
    parser = argparse.ArgumentParser(description="Bake and apply the idle pine tree sprite optimization.")
    parser.add_argument("--scene-dir", default="scene")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="Write changes; otherwise dry-run only.")
    parser.add_argument(
        "--restore-missing-from-git",
        action="store_true",
        help="Restore missing Sprite_Renderer blocks in tree-named .e files from HEAD before converting Lumber_Tree sprites.",
    )
    args = parser.parse_args()

    scene_dir = Path(args.scene_dir)
    if not scene_dir.exists():
        raise SystemExit(f"Scene directory not found: {scene_dir}")

    changed_png = bake_png(args.source, args.output, args.apply)
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: idle sprite {'would be baked' if changed_png and not args.apply else 'baked' if changed_png else 'already up to date'} -> {args.output}")

    if args.restore_missing_from_git:
        tree_named_files = sorted(path for path in scene_dir.rglob("*.e") if "tree" in path.name.lower())
        restored_files, restored_blocks = restore_missing_sprite_blocks_from_git(scene_dir, tree_named_files, args.apply)
        print(f"{mode}: {'restored' if args.apply else 'would restore'} {restored_blocks} missing Sprite_Renderer blocks in {restored_files} tree-named files from HEAD")

    texture_asset_path = args.output.as_posix()
    if texture_asset_path.startswith("res/"):
        texture_asset_path = texture_asset_path[4:]

    touched_files, updated, created = apply_lumber_tree_sprites(scene_dir, texture_asset_path, args.apply)
    print(f"{mode}: {'configured' if args.apply else 'would configure'} {touched_files} Lumber_Tree .e files")
    print(f"{mode}: {'updated' if args.apply else 'would update'} {updated} existing sprites; {'created' if args.apply else 'would create'} {created} new sprites")
    if not args.apply:
        print("Run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
