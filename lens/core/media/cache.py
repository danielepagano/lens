from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any


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

    __slots__ = ("_cache", "_maxsize", "_hits", "_misses", "warmed", "_lock")

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
        self._lock = threading.Lock()

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
