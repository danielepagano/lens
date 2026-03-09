"""Front matter pin/unpin manipulation for narrative nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, cast

import yaml

from lens.core.annotations import find_front_matter_span, parse_front_matter
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage

KB_PIN = "kb_pin"
KB_UNPIN = "kb_unpin"


def _render_front_matter(data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if v}
    if not payload:
        return ""
    yaml_text = yaml.dump(payload, default_flow_style=False).rstrip("\n")
    indented = "\n".join("    " + line for line in yaml_text.split("\n"))
    return f"[\n{indented}\n]: #"


def _set_front_matter(path: Path, data: dict[str, Any], storage: Storage) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    span = find_front_matter_span(text)

    payload = {k: v for k, v in data.items() if v}
    if not payload:
        if span is not None:
            before = lines[: span[0]]
            after = lines[span[1] :]
            new_lines = before + after
            content = "\n".join(new_lines)
            storage.write_file(path, content)
        return

    block = _render_front_matter(data)
    if span is not None:
        new_lines = lines[: span[0]] + [block] + lines[span[1] :]
    else:
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        new_lines = lines[:i] + [block, ""] + lines[i:]
    storage.write_file(path, "\n".join(new_lines))


def _mutate_front_matter(
    node: NarrativeNode,
    storage: Storage,
    fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    path = node.md_path()
    fm = parse_front_matter(path.read_text(encoding="utf-8"))
    new_fm = fn(fm)
    _set_front_matter(path, new_fm, storage)


def pin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Add kb_ids to kb_pin in the node's front matter."""

    def add(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_PIN) or [])
        current = list(raw)
        seen = set(current)
        for kid in kb_ids:
            if kid not in seen:
                current.append(kid)
                seen.add(kid)
        out = dict(d)
        out[KB_PIN] = current
        return out

    _mutate_front_matter(node, storage, add)


def unpin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Add kb_ids to kb_unpin in the node's front matter."""

    def add(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_UNPIN) or [])
        current = list(raw)
        seen = set(current)
        for kid in kb_ids:
            if kid not in seen:
                current.append(kid)
                seen.add(kid)
        out = dict(d)
        out[KB_UNPIN] = current
        return out

    _mutate_front_matter(node, storage, add)


def remove_pin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Remove kb_ids from kb_pin in the node's front matter."""

    def remove(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_PIN) or [])
        current = [x for x in raw if x not in set(kb_ids)]
        out = dict(d)
        out[KB_PIN] = current
        return out

    _mutate_front_matter(node, storage, remove)


def remove_unpin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Remove kb_ids from kb_unpin in the node's front matter."""

    def remove(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_UNPIN) or [])
        current = [x for x in raw if x not in set(kb_ids)]
        out = dict(d)
        out[KB_UNPIN] = current
        return out

    _mutate_front_matter(node, storage, remove)
