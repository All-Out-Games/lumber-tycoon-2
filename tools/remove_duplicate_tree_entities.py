from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / "scene"
TREE_MARKER = '"internal_component_type": "Lumber_Tree"'


@dataclass
class SceneEntity:
    path: Path
    aoid: int
    entity: dict
    text: str

    @property
    def previous_sibling(self) -> int | None:
        value = self.entity.get("previous_sibling")
        return int(value) if value is not None else None

    @property
    def next_sibling(self) -> int | None:
        value = self.entity.get("next_sibling")
        return int(value) if value is not None else None


def first_json_object(text: str) -> str:
    index = 0
    for _ in range(3):
        index = text.find("\n", index) + 1
        if index == 0:
            raise ValueError("missing scene metadata line")

    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "{":
        raise ValueError("missing entity object")

    start = index
    depth = 0
    in_string = False
    escape = False
    while index < len(text):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        index += 1

    raise ValueError("unclosed entity object")


def load_entities() -> list[SceneEntity]:
    entities: list[SceneEntity] = []
    for path in sorted(SCENE_DIR.glob("*.e")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) < 3:
            raise ValueError(f"{path}: missing metadata")
        aoid = int(lines[2])
        entity = json.loads(first_json_object(text))
        entities.append(SceneEntity(path=path, aoid=aoid, entity=entity, text=text))
    return entities


def tree_position(entity: SceneEntity) -> tuple[float, float] | None:
    if TREE_MARKER not in entity.text:
        return None
    pos = entity.entity.get("local_position") or {}
    if "X" not in pos or "Y" not in pos:
        return None
    return (float(pos["X"]), float(pos["Y"]))


def skip_deleted(start: int | None, step: dict[int, int | None], deleted: set[int]) -> int | None:
    seen: set[int] = set()
    current = start
    while current in deleted:
        if current in seen:
            return None
        seen.add(current)
        current = step.get(current)
    return current


def replace_sibling_value(text: str, field: str, value: int) -> str:
    pattern = rf'("{field}"\s*:\s*)\d+'
    replaced, count = re.subn(pattern, rf"\g<1>{value}", text, count=1)
    if count != 1:
        raise ValueError(f"could not replace {field}")
    return replaced


def remove_sibling_field(text: str, field: str) -> str:
    # Handles a standalone JSON object line like:   "next_sibling": 123,
    pattern = rf'\n\s*"{field}"\s*:\s*\d+,?'
    replaced, count = re.subn(pattern, "", text, count=1)
    if count != 1:
        raise ValueError(f"could not remove {field}")
    return replaced


def set_sibling_value(text: str, field: str, value: int | None) -> str:
    if re.search(rf'"{field}"\s*:', text):
        if value is None:
            return remove_sibling_field(text, field)
        return replace_sibling_value(text, field, value)

    if value is None:
        return text

    # Insert before parent if present, otherwise before the closing brace of the entity object.
    lines = text.splitlines(keepends=True)
    insert_at = None
    for i, line in enumerate(lines):
        if f'"parent"' in line:
            insert_at = i
            break
    if insert_at is None:
        for i, line in enumerate(lines):
            if line.strip() == "},":
                insert_at = i
                break
    if insert_at is None:
        raise ValueError(f"could not insert {field}")

    lines.insert(insert_at, f'  "{field}": {value},\n')
    return "".join(lines)


def main() -> None:
    entities = load_entities()
    by_id = {entity.aoid: entity for entity in entities}

    groups: dict[tuple[float, float], list[SceneEntity]] = defaultdict(list)
    for entity in entities:
        pos = tree_position(entity)
        if pos is not None:
            groups[pos].append(entity)

    delete_entities: list[SceneEntity] = []
    for duplicates in groups.values():
        if len(duplicates) <= 1:
            continue
        duplicates.sort(key=lambda entity: entity.path.name)
        delete_entities.extend(duplicates[1:])

    delete_ids = {entity.aoid for entity in delete_entities}
    prev_by_id = {entity.aoid: entity.previous_sibling for entity in entities}
    next_by_id = {entity.aoid: entity.next_sibling for entity in entities}

    sibling_updates = 0
    for entity in entities:
        if entity.aoid in delete_ids:
            continue

        new_previous = skip_deleted(entity.previous_sibling, prev_by_id, delete_ids)
        new_next = skip_deleted(entity.next_sibling, next_by_id, delete_ids)
        text = entity.text

        if new_previous != entity.previous_sibling:
            text = set_sibling_value(text, "previous_sibling", new_previous)
            sibling_updates += 1
        if new_next != entity.next_sibling:
            text = set_sibling_value(text, "next_sibling", new_next)
            sibling_updates += 1

        if text != entity.text:
            entity.path.write_text(text, encoding="utf-8")

    for entity in delete_entities:
        entity.path.unlink()

    remaining_positions: dict[tuple[float, float], list[str]] = defaultdict(list)
    for entity in load_entities():
        pos = tree_position(entity)
        if pos is not None:
            remaining_positions[pos].append(entity.path.name)
    duplicate_groups_remaining = sum(1 for files in remaining_positions.values() if len(files) > 1)

    print(f"tree_files_before={sum(1 for entity in entities if tree_position(entity) is not None)}")
    print(f"duplicate_tree_files_removed={len(delete_entities)}")
    print(f"sibling_links_updated={sibling_updates}")
    print(f"tree_files_after={sum(len(files) for files in remaining_positions.values())}")
    print(f"duplicate_position_groups_remaining={duplicate_groups_remaining}")


if __name__ == "__main__":
    main()
