from __future__ import annotations

from typing import Any, BinaryIO, Iterable

import yaml

from lens.core.media.cache import MediaCache
from lens.core.media.metadata import (
    MediaMetadata,
    MediaStore,
    filter_sidecars,
    resolve_path_metadata,
)
from lens.core.media.search import PAGE_SIZE, SearchPage, SearchResult, parse_query, score_query
from lens.core.mount import MountBackend


class MediaService:
    """Cached, metadata-aware wrapper around a ``MountBackend``.

    All read operations (``list_dir``, ``get_file_info``, ``file_exists``,
    ``get_metadata``) are cached through a shared ``MediaCache``.

    All write operations invalidate the affected cache entries and, where
    applicable, keep sidecar files in sync (e.g. delete / move also handle
    sidecars).
    """

    def __init__(self, backend: MountBackend, cache: MediaCache | None = None) -> None:
        self._backend = backend
        self._cache = cache if cache is not None else MediaCache()
        self._store = MediaStore(backend)

    @property
    def _warmed(self) -> bool:
        # Backed by the (project-lifetime) MediaCache rather than this
        # instance, since the server constructs a fresh MediaService per
        # request — see MediaCache.warmed.
        return self._cache.warmed

    @_warmed.setter
    def _warmed(self, value: bool) -> None:
        self._cache.warmed = value

    # ------------------------------------------------------------------
    # Cached read operations
    # ------------------------------------------------------------------

    def list_dir(self, subpath: str) -> list[dict[str, Any]] | None:
        self._ensure_warmed()
        key = f"list:{subpath}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        raw = self._backend.list_dir(subpath)
        if raw is None:
            return None
        filtered = filter_sidecars(raw)
        self._cache.set(key, filtered)
        return filtered

    def get_file_info(self, subpath: str) -> tuple[int, str] | None:
        key = f"info:{subpath}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        info = self._backend.get_file_info(subpath)
        if info is not None:
            self._cache.set(key, info)
        return info

    def file_exists(self, subpath: str) -> bool:
        key = f"exists:{subpath}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        exists = self._backend.file_exists(subpath)
        self._cache.set(key, exists)
        return exists

    def get_metadata(self, relative_path: str) -> MediaMetadata:
        self._ensure_warmed()
        key = f"meta:{relative_path}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        meta = self._store.get_metadata(relative_path)
        self._cache.set(key, meta)
        return meta

    # ------------------------------------------------------------------
    # Write operations (invalidate + sidecar lifecycle)
    # ------------------------------------------------------------------

    def put_file(self, dir_path: str, filename: str, data: BinaryIO) -> str:
        result = self._backend.put_file(dir_path, filename, data)
        self._cache.invalidate_prefix(f"list:{dir_path}")
        return result

    def delete(self, subpath: str) -> str:
        result = self._backend.delete(subpath)
        dir_path = _parent_dir(subpath)
        self._cache.invalidate_prefix(f"list:{dir_path}")
        self._cache.invalidate(f"info:{subpath}")
        self._cache.invalidate(f"exists:{subpath}")
        self._cache.invalidate(f"meta:{subpath}")
        self._store.delete_sidecar(subpath)
        return result

    def move(self, src: str, dst: str) -> str:
        result = self._backend.move(src, dst)
        src_dir = _parent_dir(src)
        dst_dir = _parent_dir(dst)
        self._cache.invalidate_prefix(f"list:{src_dir}")
        self._cache.invalidate_prefix(f"list:{dst_dir}")
        self._cache.invalidate(f"info:{src}")
        self._cache.invalidate(f"exists:{src}")
        self._cache.invalidate(f"meta:{src}")
        # move sidecar if present
        self._move_sidecar(src, dst)
        return result

    def delete_tree(self, subpath: str) -> None:
        self._backend.delete_tree(subpath)
        parent = _parent_dir(subpath)
        self._cache.invalidate_prefix(f"list:{parent}")
        self._cache.invalidate(f"info:{subpath}")
        self._cache.invalidate(f"exists:{subpath}")
        self._cache.invalidate(f"meta:{subpath}")
        self._store.delete_sidecar(subpath)

    def move_tree(self, src: str, dst: str) -> None:
        self._backend.move_tree(src, dst)
        src_dir = _parent_dir(src)
        dst_dir = _parent_dir(dst)
        self._cache.invalidate_prefix(f"list:{src_dir}")
        self._cache.invalidate_prefix(f"list:{dst_dir}")
        # move sidecar
        self._move_sidecar(src, dst)

    def update_metadata(self, relative_path: str, updates: dict[str, Any]) -> MediaMetadata:
        meta = self._store.update_metadata(relative_path, updates)
        self._cache.set(f"meta:{relative_path}", meta)
        return meta

    def delete_metadata(self, relative_path: str) -> None:
        self._store.delete_sidecar(relative_path)
        key = f"meta:{relative_path}"
        # Cache the now-current (sidecar-less) metadata rather than just
        # invalidating, so the next get_metadata() is a hit instead of a
        # forced round-trip to confirm the sidecar is gone. If the media
        # file itself doesn't exist there's nothing valid to cache.
        try:
            meta = self._store.get_metadata(relative_path)
        except FileNotFoundError:
            self._cache.invalidate(key)
            return
        self._cache.set(key, meta)

    # ------------------------------------------------------------------
    # Passthrough (no caching — content streaming)
    # ------------------------------------------------------------------

    def stream_file(self, subpath: str) -> tuple[Iterable[bytes], str] | None:
        return self._backend.stream_file(subpath)

    def stream_file_range(self, subpath: str, *, start: int | None, end: int | None) -> Iterable[bytes] | None:
        return self._backend.stream_file_range(subpath, start=start, end=end)

    def presign_get_object(self, subpath: str, *, expires_in: int = 3600) -> str | None:
        fn = getattr(self._backend, "presign_get_object", None)
        if fn is None:
            return None
        return fn(subpath, expires_in=expires_in)  # pyright: ignore[reportUnknownMemberType]

    # ------------------------------------------------------------------
    # Cache warm-up (bulk, lazy)
    # ------------------------------------------------------------------

    def _ensure_warmed(self) -> None:
        """Trigger a bulk cache warm-up on first use."""
        if not self._warmed:
            self._warmed = True
            self.warm_cache()

    def warm_cache(self) -> None:
        """Populate all ``list:`` and ``meta:`` cache entries in a single pass.

        Uses ``backend.walk_all`` for a bulk listing (one round-trip on S3,
        one ``os.walk`` on local) and batch-reads sidecar files so that
        subsequent calls to ``list_dir`` / ``get_metadata`` hit the cache.
        """
        all_files = self._backend.walk_all("")
        if not all_files:
            return

        file_set = set(all_files)

        # Build directory tree from file paths
        #   dir_entries[parent_dir] = set of (name, is_dir)
        dir_entries: dict[str, set[tuple[str, bool]]] = {}

        for fpath in all_files:
            parts = fpath.split("/")
            # parent dir entries
            for i in range(len(parts) - 1):
                parent = "/".join(parts[:i]) if i > 0 else ""
                dir_entries.setdefault(parent, set()).add((parts[i], True))
            # leaf entry (file or orphan sidecar)
            parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
            child = parts[-1]
            if child.endswith(".yml") and fpath[:-4] in file_set:
                continue  # sidecar — omitted from listings
            dir_entries.setdefault(parent, set()).add((child, False))

        # Write list: cache entries
        for parent_dir, entries in dir_entries.items():
            listing = [
                {"name": name, "is_dir": is_dir}
                for name, is_dir in sorted(
                    entries, key=lambda x: (not x[1], x[0].lower())
                )
            ]
            self._cache.set(f"list:{parent_dir}", listing)

        # Populate meta: cache (path-derived + sidecar merge)
        for fpath in all_files:
            if fpath.endswith(".yml"):
                continue
            meta = resolve_path_metadata(fpath)
            sidecar_path = fpath + ".yml"
            if sidecar_path in file_set:
                stream = self._backend.stream_file(sidecar_path)
                if stream is not None:
                    raw = b"".join(stream[0])
                    parsed = yaml.safe_load(raw)
                    if isinstance(parsed, dict):
                        meta = MediaMetadata(
                            relative_path=meta.relative_path,
                            name=meta.name,
                            extension=meta.extension,
                            type=meta.type,
                            extra=parsed,  # pyright: ignore[reportUnknownArgumentType]
                        )
            self._cache.set(f"meta:{fpath}", meta)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query_str: str, page: int = 1) -> SearchPage:
        """Return a paginated slice of matching media files.

        Performance comes from the cached ``list_dir`` and ``get_metadata``
        calls used internally — search results themselves are not cached.

        *page* is 1-indexed. Values below 1 are clamped to 1, values above
        the last page return an empty items list.
        The page size is always ``_PAGE_SIZE`` (20).
        """
        query = parse_query(query_str)
        results: list[SearchResult] = []

        for file_path in self._walk_files(""):
            try:
                meta = self.get_metadata(file_path)
            except FileNotFoundError:
                continue

            score = score_query(meta.flattened(), meta.extra, query)
            if score is not None:
                results.append(SearchResult(relative_path=file_path, score=score))

        results.sort(key=lambda r: (-r.score, r.relative_path))
        total_items = len(results)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)

        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        items = tuple(results[start:end])

        return SearchPage(
            items=items,
            total_items=total_items,
            total_pages=total_pages,
            page_size=PAGE_SIZE,
            current_page=page,
        )

    def _walk_files(self, subpath: str) -> list[str]:
        """Recursively enumerate all files under *subpath* using cached listings."""
        entries = self.list_dir(subpath)
        if entries is None:
            return []
        files: list[str] = []
        for entry in entries:
            name = entry["name"]
            path = f"{subpath}/{name}" if subpath else name
            if entry.get("is_dir"):
                files.extend(self._walk_files(path))
            else:
                files.append(path)
        return files

    # ------------------------------------------------------------------
    # cache management
    # ------------------------------------------------------------------

    @property
    def cache(self) -> MediaCache:
        return self._cache

    def invalidate_cache(self) -> None:
        self._cache.invalidate_all()
        self._warmed = False

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _move_sidecar(self, src: str, dst: str) -> None:
        """Move the sidecar from *src* to *dst* if it exists."""

        sp_src = src.rstrip("/") + ".yml"
        sp_dst = dst.rstrip("/") + ".yml"
        try:
            self._backend.move(sp_src, sp_dst)
        except FileNotFoundError:
            pass


def _parent_dir(subpath: str) -> str:
    clean = subpath.replace("\\", "/").rstrip("/")
    if "/" in clean:
        return clean.rsplit("/", 1)[0]
    return ""
