from pathlib import Path


SCENE_DIR = Path(__file__).resolve().parents[1] / "scene"
TREE_MARKER = '"internal_component_type": "Lumber_Tree"'
SPRITE_MARKER = '"internal_component_type": "Sprite_Renderer"'


def split_top_level_objects(body: str) -> list[str]:
    objects: list[str] = []
    i = 0
    n = len(body)

    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if body[i] != "{":
            raise ValueError(f"Expected object at offset {i}, found {body[i]!r}")

        start = i
        depth = 0
        in_string = False
        escape = False

        while i < n:
            ch = body[i]
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
                        i += 1
                        objects.append(body[start:i])
                        break
            i += 1

        if depth != 0:
            raise ValueError(f"Unclosed object starting at offset {start}")

    return objects


def rewrite_entity_file(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    if TREE_MARKER not in original or SPRITE_MARKER not in original:
        return 0

    header_lines = original.splitlines(keepends=True)[:3]
    body = original[len("".join(header_lines)) :]
    objects = split_top_level_objects(body)

    kept: list[str] = []
    removed = 0
    for obj in objects:
        if SPRITE_MARKER in obj:
            removed += 1
        else:
            kept.append(obj)

    if removed == 0:
        return 0

    rewritten = "".join(header_lines) + ",\n".join(kept)
    if original.endswith("\n"):
        rewritten += "\n"
    path.write_text(rewritten, encoding="utf-8")
    return removed


def main() -> None:
    files_changed = 0
    components_removed = 0

    for path in sorted(SCENE_DIR.glob("*.e")):
        removed = rewrite_entity_file(path)
        if removed:
            files_changed += 1
            components_removed += removed

    print(f"files_changed={files_changed}")
    print(f"components_removed={components_removed}")


if __name__ == "__main__":
    main()
