"""Filesystem-backed knowledge store for Lens projects."""

from __future__ import annotations

import io
import re
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, cast
from lens.core.exceptions import LensException
from lens.core.project import datasets_root, get_selected_datasets

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

    return type_part.lower(), key_part.lower()


def _canonical_id(type_name: str, key: str) -> str:
    return f"{type_name}.{key}".lower()


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
    _registry: ClassVar[dict[Path, KnowledgeStore]] = {}

    def __init__(
        self,
        root: Path,
        storage: Storage | None = None,
        dataset_stores: list[KnowledgeStore] | None = None,
    ) -> None:
        self._root = root
        self._knowledge = root / "knowledge"
        self._tags_path = self._knowledge / "tags.toml"
        self._tags_cache: tuple[dict[str, set[str]], dict[str, set[str]]] | None = None
        self._ext_storage = storage
        # Ordered list of dataset stores (project items take precedence; among
        # datasets, later entries in the list shadow earlier ones).
        self._dataset_stores: list[KnowledgeStore] = dataset_stores or []

    @classmethod
    def _build_dataset_stores(cls, project_root: Path) -> list[KnowledgeStore]:
        """Read selected datasets and return read-only stores for each."""
        dataset_names = get_selected_datasets(project_root)
        ds_root = datasets_root()
        stores: list[KnowledgeStore] = []
        for name in dataset_names:
            path = ds_root / name
            if path.is_dir():
                stores.append(cls(path, storage=None))
        return stores

    @classmethod
    def for_project(cls, project_root: Path, storage: Storage | None = None) -> KnowledgeStore:
        key = project_root.resolve()
        if storage is not None:
            dataset_stores = cls._build_dataset_stores(project_root)
            return cls(project_root, storage=storage, dataset_stores=dataset_stores)
        if key not in cls._registry:
            dataset_stores = cls._build_dataset_stores(project_root)
            cls._registry[key] = cls(project_root, storage=None, dataset_stores=dataset_stores)
        return cls._registry[key]

    @classmethod
    def clear_registry(cls) -> None:
        """Clear all cached instances. Intended for tests."""
        cls._registry.clear()

    def _ensure_storage(self) -> Storage:
        """Return a Storage for KB writes.

        If an external Storage was provided at construction, return it.
        Otherwise create a fresh one each call so ``_ownership_checked`` is
        never stale.
        """
        if self._ext_storage is None:
            from lens.core.project import find_git_root_from
            self._ext_storage = Storage(find_git_root_from(self._root))
        return self._ext_storage

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
            # Treat the object as existing if it lives in any dataset too.
            if path.exists() or self._dataset_store_for(canonical_id) is not None:
                return
            content = ""

        if self.exists(canonical_id) and not self._is_local(canonical_id):
            self._ensure_local(canonical_id)
        self._ensure_storage().write_file(path, content)

    def get_template(self, type_name: str) -> str | None:
        path = self._object_path(type_name.lower(), "_template")
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def set_template(self, type_name: str, content: str) -> None:
        if not _is_valid_token(type_name):
            raise ValueError(f"Invalid type format: {type_name}")
        path = self._object_path(type_name.lower(), "_template")
        self._ensure_storage().write_file(path, content)

    def get_tags(self, canonical_id: str) -> list[str]:
        """Return tags for an object. Checks project first, then datasets."""
        _, obj_to_tags = self._load_tags()
        tags = obj_to_tags.get(canonical_id)
        if tags is not None:
            return sorted(tags)
        for ds in self._dataset_stores:
            _, ds_obj_to_tags = ds._load_tags()
            tags = ds_obj_to_tags.get(canonical_id)
            if tags is not None:
                return sorted(tags)
        return []

    def get_ids_with_tag(self, tag: str) -> list[str]:
        """Return object IDs that have the given tag across project and datasets.

        The project store's ``tags.toml`` is authoritative for project-local
        objects; selected datasets contribute their own tag indexes via their
        ``tags.toml`` files. The result is the union of all matching IDs.
        """
        tag_l = tag.lower()
        objs: set[str] = set()

        # Project-local tags.
        tag_to_objs, _ = self._load_tags()
        objs.update(tag_to_objs.get(tag_l, set()))

        # Dataset tags (read-only).
        for ds in self._dataset_stores:
            ds_tag_to_objs, _ = ds._load_tags()
            objs.update(ds_tag_to_objs.get(tag_l, set()))

        return sorted(objs)

    def get_ids_with_all_tags(self, tags: list[str]) -> list[str]:
        """Return object IDs that have every given tag across project and datasets.

        For each store (project and selected datasets), compute the intersection
        of IDs that have all listed tags within that store, then union the
        per-store results.
        """
        if not tags:
            return []
        tag_lowers = [t.lower() for t in tags]

        overall: set[str] = set()

        def _intersect_for_store(tag_to_objs: dict[str, set[str]]) -> set[str]:
            store_result: set[str] | None = None
            for t in tag_lowers:
                objs = tag_to_objs.get(t, set())
                if store_result is None:
                    store_result = set(objs)
                else:
                    store_result &= objs
                if not store_result:
                    break
            return store_result or set()

        # Project-local intersection.
        tag_to_objs, _ = self._load_tags()
        overall.update(_intersect_for_store(tag_to_objs))

        # Dataset intersections.
        for ds in self._dataset_stores:
            ds_tag_to_objs, _ = ds._load_tags()
            overall.update(_intersect_for_store(ds_tag_to_objs))

        return sorted(overall) if overall else []

    def get_ids_with_tag_groups(self, groups: list[list[str]]) -> list[str]:
        """Return object IDs that match all tag groups (AND across groups, OR within).

        Each group is a list of tags; object must have at least one tag from each group.
        """
        if not groups:
            return []
        result: set[str] | None = None
        for group in groups:
            if not group:
                return []
            group_ids: set[str] = set()
            for tag in group:
                group_ids.update(self.get_ids_with_tag(tag))
            if result is None:
                result = group_ids
            else:
                result &= group_ids
            if not result:
                return []
        return sorted(result) if result else []

    def list_unique_tags(
        self,
        type_filter: str | None = None,
        prefix_filter: str | None = None,
    ) -> list[str]:
        """Return sorted unique tag values from the merged index (project + datasets).

        type_filter: only tags on objects of this type (e.g. stat.ghoul -> stat).
        prefix_filter: only tags starting with this prefix (e.g. cr:).
        Filters are ANDed.
        """
        merged_tag_to_objs: dict[str, set[str]] = {}
        merged_obj_to_tags: dict[str, set[str]] = {}

        def _merge_indexes(
            tag_to_objs: dict[str, set[str]], obj_to_tags: dict[str, set[str]]
        ) -> None:
            for tag, objs in tag_to_objs.items():
                bucket = merged_tag_to_objs.setdefault(tag, set())
                bucket.update(objs)
            for obj_id, obj_tags in obj_to_tags.items():
                bucket = merged_obj_to_tags.setdefault(obj_id, set())
                bucket.update(obj_tags)

        tag_to_objs, obj_to_tags = self._load_tags()
        _merge_indexes(tag_to_objs, obj_to_tags)
        for ds in self._dataset_stores:
            ds_tag_to_objs, ds_obj_to_tags = ds._load_tags()
            _merge_indexes(ds_tag_to_objs, ds_obj_to_tags)

        want_type = type_filter.lower() if type_filter else None
        want_prefix = prefix_filter.lower() if prefix_filter else None

        tags_set: set[str] = set()
        for obj_id, obj_tags in merged_obj_to_tags.items():
            if want_type is not None:
                try:
                    obj_type, _ = parse_id(obj_id)
                    if obj_type != want_type:
                        continue
                except ValueError:
                    continue
            for tag in obj_tags:
                if want_prefix is not None and not tag.startswith(want_prefix):
                    continue
                tags_set.add(tag)

        return sorted(tags_set)

    def traverse_by_dot_tags(
        self,
        tags: list[str],
        *,
        same_type_only: bool = False,
        max_depth: int | None = None,
    ) -> tuple[list[str], list[tuple[str, list[str]]]]:
        """BFS over tags: root = objects with every tag in tags; follow dot-tags from those objects.

        Returns (root_ids, layers). Root_ids are objects that have all listed tags (filtered by
        type if same_type_only, using tags[0]). Layers are (tag, child_ids) for tags discovered
        by following dot-tags from objects. Each tag visited at most once; cycles avoided via visited_tags.
        """
        if not tags:
            return [], []

        # Build merged tag/object indexes across project and all selected datasets.
        merged_tag_to_objs: dict[str, set[str]] = {}
        merged_obj_to_tags: dict[str, set[str]] = {}

        def _merge_indexes(tag_to_objs: dict[str, set[str]], obj_to_tags: dict[str, set[str]]) -> None:
            for tag, objs in tag_to_objs.items():
                bucket = merged_tag_to_objs.setdefault(tag, set())
                bucket.update(objs)
            for obj_id, obj_tags in obj_to_tags.items():
                bucket = merged_obj_to_tags.setdefault(obj_id, set())
                bucket.update(obj_tags)

        tag_to_objs, obj_to_tags = self._load_tags()
        _merge_indexes(tag_to_objs, obj_to_tags)
        for ds in self._dataset_stores:
            ds_tag_to_objs, ds_obj_to_tags = ds._load_tags()
            _merge_indexes(ds_tag_to_objs, ds_obj_to_tags)

        if len(tags) == 1:
            root_set = merged_tag_to_objs.get(tags[0].lower(), set())
        else:
            root_set = merged_tag_to_objs.get(tags[0].lower(), set()).copy()
            for t in tags[1:]:
                root_set &= merged_tag_to_objs.get(t.lower(), set())
                if not root_set:
                    return [], []
        root_ids = sorted(root_set)

        starting_type: str | None = None
        if same_type_only and "." in tags[0]:
            try:
                starting_type, _ = parse_id(tags[0])
            except ValueError:
                pass

        def _filter_ids_by_type(ids: list[str]) -> list[str]:
            if starting_type is None:
                return ids
            out: list[str] = []
            for oid in ids:
                if "." not in oid:
                    continue
                try:
                    t, _ = parse_id(oid)
                except ValueError:
                    continue
                if t == starting_type:
                    out.append(oid)
            return out

        def _next_tags_from_ids(ids: list[str]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for oid in ids:
                for tag in merged_obj_to_tags.get(oid.lower(), set()):
                    if "." not in tag:
                        continue
                    if same_type_only and starting_type is not None:
                        try:
                            t, _ = parse_id(tag)
                        except ValueError:
                            continue
                        if t != starting_type:
                            continue
                    t_lower = tag.lower()
                    if t_lower not in seen:
                        seen.add(t_lower)
                        out.append(tag)
                oid_lower = oid.lower()
                if "." in oid and oid_lower not in seen and oid_lower in merged_tag_to_objs:
                    if same_type_only and starting_type is not None:
                        try:
                            t, _ = parse_id(oid)
                        except ValueError:
                            pass
                        else:
                            if t == starting_type:
                                seen.add(oid_lower)
                                out.append(oid)
                    else:
                        seen.add(oid_lower)
                        out.append(oid)
            return out

        if same_type_only and starting_type is not None:
            root_ids = _filter_ids_by_type(root_ids)

        layers: list[tuple[str, list[str]]] = []
        effective_max_depth: int | None = max_depth if max_depth is None or max_depth > 0 else None
        visited_tags: set[str] = {t.lower() for t in tags}
        queue: deque[tuple[str, int]] = deque(
            (t, 1) for t in _next_tags_from_ids(root_ids)
        )

        while queue:
            t, depth = queue.popleft()
            t_lower = t.lower()
            if t_lower in visited_tags:
                continue
            visited_tags.add(t_lower)
            child_ids = sorted(merged_tag_to_objs.get(t_lower, set()))
            if same_type_only and starting_type is not None:
                child_ids = _filter_ids_by_type(child_ids)
            layers.append((t, child_ids))
            if effective_max_depth is None or depth < effective_max_depth:
                for next_tag in _next_tags_from_ids(child_ids):
                    if next_tag.lower() not in visited_tags:
                        queue.append((next_tag, depth + 1))

        return root_ids, layers

    def traverse_from_ids(
        self,
        root_ids: list[str],
        *,
        same_type_only: bool = False,
        max_depth: int | None = None,
        starting_type: str | None = None,
    ) -> tuple[list[str], list[tuple[str, list[str]]]]:
        """BFS from explicit root IDs: follow dot-tags from those objects.

        Same semantics as traverse_by_dot_tags but root set is given explicitly.
        When same_type_only is True and starting_type is None, infers from first root_id.
        """
        if not root_ids:
            return [], []

        merged_tag_to_objs: dict[str, set[str]] = {}
        merged_obj_to_tags: dict[str, set[str]] = {}

        def _merge_indexes(
            tag_to_objs: dict[str, set[str]], obj_to_tags: dict[str, set[str]]
        ) -> None:
            for tag, objs in tag_to_objs.items():
                bucket = merged_tag_to_objs.setdefault(tag, set())
                bucket.update(objs)
            for obj_id, obj_tags in obj_to_tags.items():
                bucket = merged_obj_to_tags.setdefault(obj_id, set())
                bucket.update(obj_tags)

        tag_to_objs, obj_to_tags = self._load_tags()
        _merge_indexes(tag_to_objs, obj_to_tags)
        for ds in self._dataset_stores:
            ds_tag_to_objs, ds_obj_to_tags = ds._load_tags()
            _merge_indexes(ds_tag_to_objs, ds_obj_to_tags)

        st: str | None = starting_type
        if same_type_only and st is None and root_ids:
            try:
                st, _ = parse_id(root_ids[0])
            except ValueError:
                pass

        def _filter_ids_by_type(ids: list[str]) -> list[str]:
            if st is None:
                return ids
            out: list[str] = []
            for oid in ids:
                if "." not in oid:
                    continue
                try:
                    t, _ = parse_id(oid)
                except ValueError:
                    continue
                if t == st:
                    out.append(oid)
            return out

        def _next_tags_from_ids(ids: list[str]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for oid in ids:
                for tag in merged_obj_to_tags.get(oid.lower(), set()):
                    if "." not in tag:
                        continue
                    if same_type_only and st is not None:
                        try:
                            t, _ = parse_id(tag)
                        except ValueError:
                            continue
                        if t != st:
                            continue
                    t_lower = tag.lower()
                    if t_lower not in seen:
                        seen.add(t_lower)
                        out.append(tag)
                oid_lower = oid.lower()
                if "." in oid and oid_lower not in seen and oid_lower in merged_tag_to_objs:
                    if same_type_only and st is not None:
                        try:
                            t, _ = parse_id(oid)
                        except ValueError:
                            pass
                        else:
                            if t == st:
                                seen.add(oid_lower)
                                out.append(oid)
                    else:
                        seen.add(oid_lower)
                        out.append(oid)
            return out

        filtered_root = _filter_ids_by_type(root_ids) if same_type_only and st else root_ids

        layers: list[tuple[str, list[str]]] = []
        effective_max_depth: int | None = max_depth if max_depth is None or max_depth > 0 else None
        visited_tags: set[str] = set()
        queue: deque[tuple[str, int]] = deque(
            (t, 1) for t in _next_tags_from_ids(filtered_root)
        )

        while queue:
            t, depth = queue.popleft()
            t_lower = t.lower()
            if t_lower in visited_tags:
                continue
            visited_tags.add(t_lower)
            child_ids = sorted(merged_tag_to_objs.get(t_lower, set()))
            if same_type_only and st is not None:
                child_ids = _filter_ids_by_type(child_ids)
            layers.append((t, child_ids))
            if effective_max_depth is None or depth < effective_max_depth:
                for next_tag in _next_tags_from_ids(child_ids):
                    if next_tag.lower() not in visited_tags:
                        queue.append((next_tag, depth + 1))

        return filtered_root, layers

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
        self._ensure_local(canonical_id)
        tag_to_objs, obj_to_tags = self._load_tags()
        for tag in tags:
            if not _validate_tag(tag):
                continue
            tag_to_objs.setdefault(tag.lower(), set()).add(canonical_id.lower())
            obj_to_tags.setdefault(canonical_id.lower(), set()).add(tag.lower())
        self._save_tags(tag_to_objs, obj_to_tags)
        return None

    def remove_tags(self, canonical_id: str, tags: list[str]) -> None:
        self._ensure_local(canonical_id)
        tag_to_objs, obj_to_tags = self._load_tags()
        for tag in tags:
            if tag.lower() in tag_to_objs:
                tag_to_objs[tag.lower()].discard(canonical_id.lower())
            if canonical_id.lower() in obj_to_tags:
                obj_to_tags[canonical_id.lower()].discard(tag.lower())
        self._save_tags(tag_to_objs, obj_to_tags)

    def get_objects_with_links(
        self, raw_ids: list[str]
    ) -> tuple[list[str], dict[str, KnowledgeObject]]:
        """Parse IDs (+ suffix expands linked objects) and fetch them.

        Returns the ordered list of all IDs (explicit + linked, in pinning order)
        and the full objects dict for lookup.
        """
        ordered_roots: list[str] = []
        seen: set[str] = set()
        onehop_expand: set[str] = set()
        recursive_expand: set[str] = set()

        for raw in raw_ids:
            recursive = raw.endswith("++")
            onehop = (not recursive) and raw.endswith("+")
            base = raw[:-2] if recursive else (raw[:-1] if onehop else raw)
            try:
                type_part, key_part = parse_id(base)
            except ValueError:
                continue
            cid = _canonical_id(type_part, key_part)

            if cid not in seen:
                ordered_roots.append(cid)
                seen.add(cid)

            if recursive:
                recursive_expand.add(cid)
            elif onehop:
                onehop_expand.add(cid)

        objects = self.get_objects(ordered_roots)
        ordered_ids: list[str] = list(objects.keys())
        visited: set[str] = set(ordered_ids)

        # Expand one hop for roots explicitly marked with "+", but not "++".
        if onehop_expand and objects:
            subset: dict[str, KnowledgeObject] = {
                cid: objects[cid]
                for cid in ordered_roots
                if cid in objects and cid in onehop_expand
            }
            for linked_id in self._collect_linked_ids(subset):
                if linked_id in visited:
                    continue
                visited.add(linked_id)
                linked_obj = self._fetch_one(linked_id)
                if linked_obj is None:
                    continue
                objects[linked_id] = linked_obj
                ordered_ids.append(linked_id)

        # Recursively expand for roots explicitly marked with "++".
        if recursive_expand and objects:
            roots = [
                cid for cid in ordered_roots if cid in objects and cid in recursive_expand
            ]
            if roots:
                self._expand_linked_bfs(
                    ordered_ids=ordered_ids,
                    objects=objects,
                    visited=visited,
                    roots=roots,
                )

        return ordered_ids, objects

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
            missing = [x for x in linked if x not in result]
            for cid in missing:
                obj = self._fetch_one(cid)
                if obj is not None:
                    result[cid] = obj

        return result

    def _fetch_local(self, canonical_id: str) -> KnowledgeObject | None:
        """Fetch an object from *this* store only (no dataset fallback)."""
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

    def _fetch_one(self, canonical_id: str) -> KnowledgeObject | None:
        """Fetch an object, falling back to dataset stores if not found locally.

        Among datasets the *last* entry in the list wins (later datasets shadow
        earlier ones), matching the import-order precedence rule.
        """
        obj = self._fetch_local(canonical_id)
        if obj is not None:
            return obj
        for ds in reversed(self._dataset_stores):
            obj = ds._fetch_local(canonical_id)
            if obj is not None:
                return obj
        return None

    def _is_local(self, canonical_id: str) -> bool:
        """Return True if *canonical_id* exists in this store's own knowledge dir."""
        try:
            type_name, key = parse_id(canonical_id)
        except ValueError:
            return False
        return self._object_path(type_name, key).exists()

    def exists(self, canonical_id: str) -> bool:
        """Return True if *canonical_id* exists in this store or any dataset store."""
        try:
            type_name, key = parse_id(canonical_id)
        except ValueError:
            return False
        if self._object_path(type_name, key).exists():
            return True
        for ds in self._dataset_stores:
            if ds._is_local(canonical_id):
                return True
        return False

    def _dataset_store_for(self, canonical_id: str) -> KnowledgeStore | None:
        """Return the dataset store that owns *canonical_id* (last-wins), or None."""
        for ds in reversed(self._dataset_stores):
            if ds._fetch_local(canonical_id) is not None:
                return ds
        return None

    def ensure_local_copy(self, canonical_id: str) -> None:
        """Materialize a project-local copy if the object exists only in a dataset.

        No-op if the object is already local or does not exist. Use before
        mutating dataset objects so the change is written to the project.
        """
        self._ensure_local(canonical_id)

    def _ensure_local(self, canonical_id: str) -> None:
        """Copy-on-write: if *canonical_id* lives only in a dataset, materialise
        a project-local copy (including its tags) so that subsequent mutations
        apply to the project rather than the read-only dataset.
        """
        if self._is_local(canonical_id):
            return
        ds = self._dataset_store_for(canonical_id)
        if ds is None:
            return  # doesn't exist anywhere; let the caller surface the error
        obj = ds._fetch_local(canonical_id)
        if obj is None:
            return
        type_name, key = parse_id(canonical_id)
        path = self._object_path(type_name, key)
        self._ensure_storage().write_file(path, obj.text)
        if obj.tags:
            tag_to_objs, obj_to_tags = self._load_tags()
            cid_lower = canonical_id.lower()
            for tag in obj.tags:
                tag_to_objs.setdefault(tag.lower(), set()).add(cid_lower)
                obj_to_tags.setdefault(cid_lower, set()).add(tag.lower())
            self._save_tags(tag_to_objs, obj_to_tags)

    def _collect_linked_ids(self, objects: dict[str, KnowledgeObject]) -> list[str]:
        linked: list[str] = []
        for obj in objects.values():
            for tag in obj.tags:
                if "." not in tag:
                    continue
                try:
                    type_part, key_part = parse_id(tag)
                    cid = _canonical_id(type_part, key_part)
                    if cid not in linked:
                        linked.append(cid)
                except ValueError:
                    continue
        return linked

    def _expand_linked_bfs(
        self,
        *,
        ordered_ids: list[str],
        objects: dict[str, KnowledgeObject],
        visited: set[str],
        roots: list[str],
    ) -> None:
        queue: deque[str] = deque(roots)
        expanded: set[str] = set()

        while queue:
            cid = queue.popleft()
            if cid in expanded:
                continue
            expanded.add(cid)

            obj = objects.get(cid)
            if obj is None:
                continue

            for linked_id in self._collect_linked_ids({cid: obj}):
                if linked_id not in visited:
                    visited.add(linked_id)
                    linked_obj = self._fetch_one(linked_id)
                    if linked_obj is None:
                        continue
                    objects[linked_id] = linked_obj
                    ordered_ids.append(linked_id)

                if linked_id in objects and linked_id not in expanded:
                    queue.append(linked_id)

    def copy_object(self, source_id: str, target_id: str) -> None:
        """Copy object to a new ID. Target must be valid and unused; type may differ.

        The source may live in a dataset; the copy is always created in this
        (project) store.
        """
        _, src_key = parse_id(source_id)
        tgt_type, tgt_key = parse_id(target_id)
        obj = self._fetch_one(source_id)
        if obj is None:
            raise ValueError(f"Object '{source_id}' does not exist")
        if self._fetch_one(target_id) is not None:
            raise ValueError(f"Object '{target_id}' already exists")
        dst_path = self._object_path(tgt_type, tgt_key)
        storage = self._ensure_storage()
        if self._is_local(source_id):
            src_type, _ = parse_id(source_id)
            src_path = self._object_path(src_type, src_key)
            storage.copy_file(src_path, dst_path)
        else:
            storage.write_file(dst_path, obj.text)
        tag_to_objs, obj_to_tags = self._load_tags()
        src_id_lower = source_id.lower()
        tgt_id_lower = target_id.lower()
        for tag in obj.tags:
            t_lower = tag.lower()
            tag_to_objs.setdefault(t_lower, set()).add(tgt_id_lower)
            obj_to_tags.setdefault(tgt_id_lower, set()).add(t_lower)
        if src_id_lower in tag_to_objs:
            objs_with_src_as_tag = tag_to_objs[src_id_lower]
            tag_to_objs.setdefault(tgt_id_lower, set()).update(objs_with_src_as_tag)
            for oid in objs_with_src_as_tag:
                obj_to_tags.setdefault(oid, set()).add(tgt_id_lower)
        self._save_tags(tag_to_objs, obj_to_tags)

    def rename_object(self, old_id: str, new_id: str) -> None:
        """Rename object to a new ID. Target must be valid and unused; type may differ.

        Renaming a dataset-only item is not supported; use copy instead.
        """
        old_type, old_key = parse_id(old_id)
        new_type, new_key = parse_id(new_id)
        if self._fetch_one(old_id) is None:
            raise ValueError(f"Object '{old_id}' does not exist")
        if not self._is_local(old_id):
            raise ValueError(
                f"Object '{old_id}' is from a dataset and cannot be renamed; "
                "use 'kb copy' to create a project-local copy"
            )
        if self._fetch_one(new_id) is not None:
            raise ValueError(f"Object '{new_id}' already exists")
        src_path = self._object_path(old_type, old_key)
        dst_path = self._object_path(new_type, new_key)
        storage = self._ensure_storage()
        storage.rename(src_path, dst_path)
        tag_to_objs, obj_to_tags = self._load_tags()
        old_lower = old_id.lower()
        new_lower = new_id.lower()

        tags = obj_to_tags.pop(old_lower, set())
        tags_normalized = {t.lower() for t in tags}
        for tag in tags_normalized:
            tag_to_objs.setdefault(tag, set()).discard(old_lower)
            tag_to_objs.setdefault(tag, set()).add(new_lower)
        if tags_normalized:
            obj_to_tags[new_lower] = {
                new_lower if t == old_lower else t for t in tags_normalized
            }

        if old_lower in tag_to_objs:
            objs_with_old_as_tag = tag_to_objs.pop(old_lower)
            tag_to_objs.setdefault(new_lower, set()).update(objs_with_old_as_tag)
            for oid in objs_with_old_as_tag:
                if oid != old_lower and oid in obj_to_tags:
                    obj_to_tags[oid].discard(old_lower)
                    obj_to_tags[oid].add(new_lower)

        self._save_tags(tag_to_objs, obj_to_tags)

    def list_types(self) -> list[str]:
        """Return all unique type names across project and dataset stores."""
        types: set[str] = set()
        if self._knowledge.exists():
            for d in self._knowledge.iterdir():
                if d.is_dir() and d.name not in ("__pycache__",):
                    types.add(d.name)
        for ds in self._dataset_stores:
            types.update(ds.list_types())
        return sorted(types)

    def list_ids(self, type_filter: str | None = None) -> list[str]:
        """Return all canonical IDs, optionally filtered by type, across project and datasets."""
        ids: set[str] = set()
        type_lower = type_filter.lower() if type_filter else None

        def _scan_store(store: "KnowledgeStore") -> None:
            if not store._knowledge.exists():
                return
            dirs = [store._knowledge / type_lower] if type_lower else (
                [d for d in store._knowledge.iterdir() if d.is_dir() and d.name != "__pycache__"]
            )
            for type_dir in dirs:
                if not type_dir.is_dir():
                    continue
                for f in type_dir.glob("*.md"):
                    if f.stem != "_template":
                        ids.add(f"{type_dir.name}.{f.stem}")

        _scan_store(self)
        for ds in self._dataset_stores:
            _scan_store(ds)
        return sorted(ids)

    def delete_object(self, canonical_id: str) -> None:
        # Deleting a dataset-only item is a no-op.
        if not self._is_local(canonical_id):
            return
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


def validate_ids_exist(project_root: Path, ids: list[str]) -> None:
    """Raise LensException if any id in *ids* does not exist in the knowledge store.

    IDs may include the + suffix for linked expansion; the base id is checked.
    """
    if not ids:
        return
    kb = KnowledgeStore.for_project(project_root)
    missing: list[str] = []
    for kid in ids:
        base = kid.rstrip("+")
        if not kb.exists(base):
            missing.append(kid)
    if missing:
        raise LensException(
            f"knowledge object(s) do not exist: {', '.join(missing)}"
        )
