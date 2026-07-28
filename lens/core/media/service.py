from __future__ import annotations

from typing import Any, BinaryIO, Iterable

from lens.core.media.cache import MediaCache
from lens.core.media.metadata import (
    MediaMetadata,
    MediaStore,
    filter_sidecars,
)
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

    # ------------------------------------------------------------------
    # Cached read operations
    # ------------------------------------------------------------------

    def list_dir(self, subpath: str) -> list[dict[str, Any]] | None:
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
        self._cache.invalidate(f"meta:{relative_path}")

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
    # cache management
    # ------------------------------------------------------------------

    @property
    def cache(self) -> MediaCache:
        return self._cache

    def invalidate_cache(self) -> None:
        self._cache.invalidate_all()

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
