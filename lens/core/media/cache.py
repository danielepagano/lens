from __future__ import annotations

from collections import OrderedDict
from typing import Any


class MediaCache:
    """LRU cache for media enumeration and metadata results.

    Single-process, not thread-safe.  All write operations on the media
    subsystem should call ``invalidate`` or ``invalidate_prefix`` so that
    subsequent reads see fresh data.

    Key namespace convention:
      ``list:{subpath}`` — directory listing
      ``info:{subpath}`` — ``(size_bytes, content_type)``
      ``meta:{subpath}`` — ``MediaMetadata``
      ``exists:{subpath}`` — ``bool``
    """

    __slots__ = ("_cache", "_maxsize", "_hits", "_misses", "warmed")

    def __init__(self, maxsize: int = 1000) -> None:
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0
        # Tracks whether a bulk `MediaService.warm_cache()` pass has already
        # populated this cache. Lives here (not on MediaService) because the
        # server constructs a fresh MediaService per request but reuses one
        # MediaCache per project — see lens/server/dependencies.py.
        self.warmed = False

    def get(self, key: str) -> Any | None:
        try:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        except KeyError:
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        self._trim()

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        to_del = [k for k in self._cache if k.startswith(prefix)]
        for k in to_del:
            del self._cache[k]

    def invalidate_all(self) -> None:
        self._cache.clear()
        self.warmed = False

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
        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def __repr__(self) -> str:
        return f"MediaCache(size={self.size}/{self._maxsize}, hits={self._hits}, misses={self._misses})"
