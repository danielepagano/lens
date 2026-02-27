"""Filesystem-backed knowledge store for Lens projects."""

from __future__ import annotations

import io
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import tomli_w

from lens.core.storage import Storage

_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _is_valid_token(value: str) -> bool:
    return bool(_VALUE_PATTERN.fullmatch(value))


def _is_valid_key(value: str) -> bool:
    return bool(_KEY_PATTERN.fullmatch(value))


def _validate_tag(tag: str) -> bool:
    if not tag:
        return False
    if ":" in tag and "." in tag:
        return False
    if ":" in tag:
        parts = tag.split(":", 1)
        return len(parts) == 2 and all(_is_valid_token(p) for p in parts)
    if "." in tag:
        parts = tag.split(".", 1)
        return len(parts) == 2 and all(_is_valid_token(p) for p in parts)
    return _is_valid_token(tag)


def parse_id(canonical_id: str, default_type: str | None = None) -> tuple[str, str]:
    if "." in canonical_id:
        type_part, key_part = canonical_id.split(".", 1)
        if not key_part:
            raise ValueError(
                f"Invalid canonical ID format: key cannot be empty (got '{canonical_id}')"
            )
    elif default_type:
        type_part = default_type
        key_part = canonical_id
    else:
        raise ValueError(f"Invalid canonical ID format: {canonical_id}")

    if not _is_valid_token(type_part):
        raise ValueError(f"Invalid type format: {type_part}")
    if not _is_valid_key(key_part):
        raise ValueError(f"Invalid key format: {key_part}")

    return type_part, key_part


def _canonical_id(type_name: str, key: str) -> str:
    return f"{type_name}.{key}"


@dataclass
class KnowledgeObject:
    type: str
    id: str
    text: str
    tags: list[str] = field(default_factory=lambda: cast(list[str], []))

    def format(self, *, include_comments: bool = False) -> str:
        from lens.core.annotations import strip_markdown_comments
        text = self.text if include_comments else strip_markdown_comments(self.text)
        lines: list[str] = [f"KB[{self.id!r}]"]
        lines.append("  " + text.replace("\n", "\n  "))
        if self.tags:
            lines.append(f"  TAGS={', '.join(self.tags)}")
        return "\n".join(lines) + "\n"

    def __repr__(self) -> str:
        return self.format()


class KnowledgeStore:
    def __init__(self, root: Path, storage: Storage | None = None) -> None:
        self._root = root
        self._knowledge = root / "knowledge"
        self._tags_path = self._knowledge / "tags.toml"
        self._tags_cache: tuple[dict[str, set[str]], dict[str, set[str]]] | None = None
        self._storage = storage

    def _ensure_storage(self) -> Storage:
        """Return the current Storage instance, creating one lazily if needed.

        ``self._root`` is already the validated project root; we only need to
        locate the enclosing git repository.
        """
        if self._storage is not None:
            return self._storage
        from lens.core.project import find_git_root_from
        self._storage = Storage(find_git_root_from(self._root))
        return self._storage

    def _object_path(self, type_name: str, key: str) -> Path:
        return self._knowledge / type_name / f"{key}.md"

    def _load_tags(
        self,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        if self._tags_cache is not None:
            return self._tags_cache
        tag_to_objs: dict[str, set[str]] = {}
        obj_to_tags: dict[str, set[str]] = {}
        if not self._tags_path.exists():
            self._tags_cache = (tag_to_objs, obj_to_tags)
            return self._tags_cache
        with self._tags_path.open("rb") as f:
            data = tomllib.load(f)
        if "tags" in data and isinstance(data["tags"], dict):
            for tag, vals in cast(dict[str, Any], data["tags"]).items():
                if isinstance(vals, list):
                    tag_to_objs[str(tag)] = {str(x) for x in cast(list[Any], vals)}
        if "objects" in data and isinstance(data["objects"], dict):
            for obj_id, vals in cast(dict[str, Any], data["objects"]).items():
                if isinstance(vals, list):
                    obj_to_tags[str(obj_id)] = {
                        str(x) for x in cast(list[Any], vals)
                    }
        if not obj_to_tags and tag_to_objs:
            for tag, objs in tag_to_objs.items():
                for obj_id in objs:
                    obj_to_tags.setdefault(obj_id, set()).add(tag)
        self._tags_cache = (tag_to_objs, obj_to_tags)
        return self._tags_cache

    def _save_tags(
        self,
        tag_to_objs: dict[str, set[str]],
        obj_to_tags: dict[str, set[str]],
    ) -> None:
        self._tags_cache = (tag_to_objs, obj_to_tags)
        tags_serial: dict[str, list[str]] = {
            k: sorted(v) for k, v in tag_to_objs.items() if v
        }
        objects_serial: dict[str, list[str]] = {
            k: sorted(v) for k, v in obj_to_tags.items() if v
        }
        payload: dict[str, object] = {}
        if tags_serial:
            payload["tags"] = tags_serial
        if objects_serial:
            payload["objects"] = objects_serial
        buf = io.BytesIO()
        tomli_w.dump(cast(Any, payload), buf)
        self._ensure_storage().write_file_bytes(self._tags_path, buf.getvalue())

    def store_object(
        self,
        canonical_id: str,
        content: str | None = None,
        use_template: bool = False,
    ) -> None:
        type_name, key = parse_id(canonical_id)
        path = self._object_path(type_name, key)

        if use_template:
            template = self.get_template(type_name)
            content = template if template is not None else ""

        if content is None:
            if path.exists():
                return
            content = ""

        self._ensure_storage().write_file(path, content)

    def get_template(self, type_name: str) -> str | None:
        path = self._object_path(type_name, "_template")
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def set_template(self, type_name: str, content: str) -> None:
        if not _is_valid_token(type_name):
            raise ValueError(f"Invalid type format: {type_name}")
        path = self._object_path(type_name, "_template")
        self._ensure_storage().write_file(path, content)

    def get_tags(self, canonical_id: str) -> list[str]:
        _, obj_to_tags = self._load_tags()
        return sorted(obj_to_tags.get(canonical_id, set()))

    def get_invalid_dot_tags(self, tags: list[str]) -> list[str]:
        """Return dot-tags that reference non-existent objects."""
        invalid: list[str] = []
        for tag in tags:
            if "." not in tag:
                continue
            try:
                parse_id(tag)
            except ValueError:
                continue
            if self._fetch_one(tag) is None:
                invalid.append(tag)
        return invalid

    def add_tags(self, canonical_id: str, tags: list[str]) -> str | None:
        """Add tags to an object. Returns error message if object does not exist, else None."""
        parse_id(canonical_id)
        if self._fetch_one(canonical_id) is None:
            return f"Object '{canonical_id}' does not exist"
        tag_to_objs, obj_to_tags = self._load_tags()
        for tag in tags:
            if not _validate_tag(tag):
                continue
            tag_to_objs.setdefault(tag, set()).add(canonical_id)
            obj_to_tags.setdefault(canonical_id, set()).add(tag)
        self._save_tags(tag_to_objs, obj_to_tags)
        return None

    def remove_tags(self, canonical_id: str, tags: list[str]) -> None:
        tag_to_objs, obj_to_tags = self._load_tags()
        for tag in tags:
            if tag in tag_to_objs:
                tag_to_objs[tag].discard(canonical_id)
            if canonical_id in obj_to_tags:
                obj_to_tags[canonical_id].discard(tag)
        self._save_tags(tag_to_objs, obj_to_tags)

    def get_objects_with_links(
        self, raw_ids: list[str]
    ) -> tuple[list[str], dict[str, KnowledgeObject]]:
        """Parse IDs (! suffix expands linked objects) and fetch them.

        Returns the ordered list of requested IDs and the full objects dict
        (which may contain additional linked objects for those marked with !).
        """
        ordered: list[str] = []
        seen: set[str] = set()
        expand_linked_for: set[str] = set()
        for raw in raw_ids:
            linked = raw.endswith("!")
            cid = raw[:-1] if linked else raw
            try:
                parse_id(cid)
            except ValueError:
                continue
            if cid not in seen:
                ordered.append(cid)
                seen.add(cid)
            if linked:
                expand_linked_for.add(cid)
        objects = self.get_objects(
            ordered,
            expand_linked_for=expand_linked_for if expand_linked_for else None,
        )
        return ordered, objects

    def get_objects(
        self,
        ids: list[str],
        get_linked: bool = False,
        expand_linked_for: set[str] | None = None,
    ) -> dict[str, KnowledgeObject]:
        validated: list[str] = []
        seen: set[str] = set()
        for cid in ids:
            try:
                parse_id(cid)
                if cid not in seen:
                    validated.append(cid)
                    seen.add(cid)
            except ValueError:
                continue

        result: dict[str, KnowledgeObject] = {}
        for cid in validated:
            obj = self._fetch_one(cid)
            if obj is not None:
                result[cid] = obj

        to_expand: set[str] = (
            expand_linked_for
            if expand_linked_for is not None
            else (set(validated) if get_linked else set[str]())
        )
        if to_expand and result:
            subset = {k: v for k, v in result.items() if k in to_expand}
            linked = self._collect_linked_ids(subset)
            missing = linked - result.keys()
            for cid in missing:
                obj = self._fetch_one(cid)
                if obj is not None:
                    result[cid] = obj

        return result

    def _fetch_one(self, canonical_id: str) -> KnowledgeObject | None:
        try:
            type_name, key = parse_id(canonical_id)
        except ValueError:
            return None
        path = self._object_path(type_name, key)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        tags = self.get_tags(canonical_id)
        return KnowledgeObject(type=type_name, id=canonical_id, text=text, tags=tags)

    def _collect_linked_ids(self, objects: dict[str, KnowledgeObject]) -> set[str]:
        linked: set[str] = set()
        for obj in objects.values():
            for tag in obj.tags:
                if "." not in tag:
                    continue
                try:
                    type_part, key_part = parse_id(tag)
                    linked.add(_canonical_id(type_part, key_part))
                except ValueError:
                    continue
        return linked

    def delete_object(self, canonical_id: str) -> None:
        type_name, key = parse_id(canonical_id)
        path = self._object_path(type_name, key)
        self._ensure_storage().delete_file(path)

        tag_to_objs, obj_to_tags = self._load_tags()
        for _, tags in list(obj_to_tags.items()):
            tags.discard(canonical_id)
        for tag in list(tag_to_objs.keys()):
            tag_to_objs[tag].discard(canonical_id)
        if canonical_id in tag_to_objs:
            del tag_to_objs[canonical_id]
        obj_to_tags.pop(canonical_id, None)
        self._save_tags(tag_to_objs, obj_to_tags)
