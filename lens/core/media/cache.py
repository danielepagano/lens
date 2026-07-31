from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from lens.core.media.search import SearchRecord, build_search_record

DEFAULT_SEARCH_INDEX_LIMIT = 10_000


class MediaCache:
    """LRU cache for media enumeration and metadata results.

    Shared per-project across requests (see ``lens/server/dependencies.py``),
    and the server dispatches sync route handlers onto a real thread pool —
    so this cache genuinely sees concurrent access and every mutating /
    iterating operation is guarded by a lock. All write operations on the
    media subsystem should call ``invalidate`` or ``invalidate_prefix`` so
    that subsequent reads see fresh data.

    Key namespace convention:
      ``list:{subpath}`` — directory listing
      ``info:{subpath}`` — ``(size_bytes, content_type)``
      ``meta:{subpath}`` — ``MediaMetadata``
      ``exists:{subpath}`` — ``bool``
    """

    __slots__ = ("_cache", "_maxsize", "_hits", "_misses", "warmed", "_lock", "search_index")

    def __init__(self, maxsize: int = 1000, search_index_limit: int = DEFAULT_SEARCH_INDEX_LIMIT) -> None:
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0
        # Tracks whether a bulk `MediaService.warm_cache()` pass has already
        # populated this cache. Lives here (not on MediaService) because the
        # server constructs a fresh MediaService per request but reuses one
        # MediaCache per project — see lens/server/dependencies.py.
        self.warmed = False
        self._lock = threading.Lock()
        # Full (non-LRU) search index, kept alongside the LRU rather than in
        # it — search needs every file's precomputed record to stay
        # available, which an eviction policy can't promise. See
        # MediaSearchIndex.
        self.search_index = MediaSearchIndex(limit=search_index_limit)

    def get(self, key: str) -> Any | None:
        with self._lock:
            try:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            except KeyError:
                self._misses += 1
                return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            self._trim()

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in to_del:
                del self._cache[k]

    def invalidate_all(self) -> None:
        with self._lock:
            self._cache.clear()
            self.warmed = False
        self.search_index.clear()

    def claim_warm(self) -> bool:
        """Atomically claim the right to run a bulk warm pass.

        Returns ``True`` for exactly one caller (setting ``warmed`` in the
        same locked step) and ``False`` for anyone else until the cache is
        next invalidated — without this, two concurrent cold requests could
        both observe ``warmed is False`` and both kick off a redundant full
        ``MediaService.warm_cache()`` mount scan.
        """
        with self._lock:
            if self.warmed:
                return False
            self.warmed = True
            return True

    def ensure_capacity(self, min_size: int) -> None:
        """Raise ``maxsize`` if needed so at least *min_size* entries fit.

        Used by a bulk warm pass: evicting entries mid-pass because the
        pass itself exceeds the default LRU bound would defeat the point of
        warming (``warmed`` would stay ``True`` while coverage silently
        shrank back to partial).
        """
        with self._lock:
            if min_size > self._maxsize:
                self._maxsize = min_size

    # ------------------------------------------------------------------
    # introspection / stats
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_ratio(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    def stats(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": self.hit_ratio,
        }

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _trim(self) -> None:
        # Called only from within a `with self._lock:` block above.
        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def __repr__(self) -> str:
        return f"MediaCache(size={self.size}/{self._maxsize}, hits={self._hits}, misses={self._misses})"


class MediaSearchIndex:
    """Full (non-evicting) cache of precomputed ``SearchRecord``\\ s, one per file.

    This exists to make search never touch the backend at all: it either
    holds a record for *every* file in the project, or it holds nothing.
    There is no partial/LRU middle ground and no on-demand fallback to the
    mount backend — a search against a project whose file count exceeds
    *limit* must fail loudly (see ``locked``) rather than silently paying
    per-file S3 reads (slow and, on S3-billed mounts, an actual cost) or
    silently returning an incomplete result set. Raise *limit* and
    re-warm to recover.

    Entries are kept in sync incrementally by the ``MediaService`` write
    paths (``set``/``remove``/``rename``) rather than invalidated wholesale,
    so a single new/edited/moved file costs one dict operation, never a
    rescan or backend call.
    """

    __slots__ = ("_records", "_limit", "_locked", "_lock")

    def __init__(self, limit: int = DEFAULT_SEARCH_INDEX_LIMIT) -> None:
        self._records: dict[str, SearchRecord] = {}
        self._limit = limit
        self._locked = False
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def locked(self) -> bool:
        """``True`` once the tracked file count has exceeded *limit*.

        While locked, the index holds no records and every write is a
        no-op — it stays locked until ``clear()`` (full cache invalidation)
        or ``begin_bulk_load()`` (a fresh warm pass) resets it.
        """
        with self._lock:
            return self._locked

    def get(self, relative_path: str) -> SearchRecord | None:
        with self._lock:
            if self._locked:
                return None
            return self._records.get(relative_path)

    def set(self, relative_path: str, flattened: dict[str, Any]) -> None:
        with self._lock:
            if self._locked:
                return
            if relative_path not in self._records and len(self._records) >= self._limit:
                self._lock_over_capacity()
                return
            self._records[relative_path] = build_search_record(flattened)

    def remove(self, relative_path: str) -> None:
        with self._lock:
            if self._locked:
                return
            self._records.pop(relative_path, None)

    def rename(self, src: str, dst: str, path_fields: dict[str, Any]) -> None:
        """Move the record at *src* to *dst*, keeping its non-path-derived fields.

        *path_fields* is *dst*'s path-derived flattened dict — just the 4
        reserved keys (no I/O needed, pure string parsing; see
        ``resolve_path_metadata``). A move doesn't touch sidecar content, so
        every other (``extra``-derived) key from the existing record carries
        over unchanged rather than being re-read from the backend.
        """
        with self._lock:
            if self._locked:
                return
            record = self._records.pop(src, None)
            if record is None:
                return
            if dst not in self._records and len(self._records) >= self._limit:
                self._lock_over_capacity()
                return
            new_flattened = dict(record.flattened)
            new_flattened.update(path_fields)
            self._records[dst] = build_search_record(new_flattened)

    def begin_bulk_load(self, total_files: int) -> bool:
        """Reset the index ahead of a full warm pass over *total_files* files.

        Returns ``True`` if *total_files* fits under the cap — the caller
        should proceed populating via ``set``. Returns ``False`` (and
        leaves the index locked+empty) if it doesn't; the caller must not
        populate it in that case.
        """
        with self._lock:
            self._records.clear()
            self._locked = total_files > self._limit
            return not self._locked

    def items(self) -> list[tuple[str, SearchRecord]]:
        with self._lock:
            if self._locked:
                return []
            return list(self._records.items())

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._locked = False

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, relative_path: str) -> bool:
        with self._lock:
            return (not self._locked) and relative_path in self._records

    def _lock_over_capacity(self) -> None:
        # Called only from within a `with self._lock:` block above.
        self._records.clear()
        self._locked = True
