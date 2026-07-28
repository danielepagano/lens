"""Unit tests for MediaCache (LRU, size-bound)."""

from __future__ import annotations

from lens.core.media.cache import MediaCache


class TestMediaCache:
    def test_get_miss_returns_none(self) -> None:
        c = MediaCache(maxsize=10)
        assert c.get("nope") is None

    def test_set_and_get(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("a", 42)
        assert c.get("a") == 42

    def test_get_is_lru(self) -> None:
        c = MediaCache(maxsize=3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")   # promotes a to most-recent
        c.set("d", 4)  # should evict b (oldest)
        assert c.get("a") == 1
        assert c.get("b") is None  # evicted
        assert c.get("c") == 3
        assert c.get("d") == 4

    def test_eviction_fifo_when_maxsize_exceeded(self) -> None:
        c = MediaCache(maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        assert c.size == 2
        c.set("c", 3)   # evicts a
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_set_replaces_existing_key(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("a", 1)
        c.set("a", 99)
        assert c.get("a") == 99
        assert c.size == 1

    def test_invalidate_single_key(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("a", 1)
        c.set("b", 2)
        c.invalidate("a")
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.size == 1

    def test_invalidate_missing_key_does_not_raise(self) -> None:
        c = MediaCache(maxsize=10)
        c.invalidate("nope")  # should not raise

    def test_invalidate_prefix(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("list:a", 1)
        c.set("list:b", 2)
        c.set("info:a", 3)
        c.set("meta:a", 4)
        c.invalidate_prefix("list:")
        assert c.get("list:a") is None
        assert c.get("list:b") is None
        assert c.get("info:a") == 3
        assert c.get("meta:a") == 4

    def test_invalidate_prefix_no_match(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("a", 1)
        c.invalidate_prefix("z:")
        assert c.get("a") == 1
        assert c.size == 1

    def test_invalidate_all(self) -> None:
        c = MediaCache(maxsize=10)
        c.set("a", 1)
        c.set("b", 2)
        c.invalidate_all()
        assert c.size == 0
        assert c.get("a") is None

    def test_stats(self) -> None:
        c = MediaCache(maxsize=100)
        c.set("a", 1)
        c.get("a")  # hit
        c.get("a")  # hit
        c.get("b")  # miss
        s = c.stats()
        assert s["size"] == 1
        assert s["maxsize"] == 100
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["hit_ratio"] == 2 / 3

    def test_hit_ratio_zero_on_empty(self) -> None:
        c = MediaCache(maxsize=10)
        assert c.hit_ratio == 0.0

    def test_set_trims_to_maxsize(self) -> None:
        c = MediaCache(maxsize=3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.set("d", 4)
        assert c.size == 3
        assert c.get("a") is None

    def test_repr(self) -> None:
        c = MediaCache(maxsize=100)
        c.set("a", 1)
        r = repr(c)
        assert "MediaCache" in r
        assert "size=1/100" in r

    def test_maxsize_property(self) -> None:
        c = MediaCache(maxsize=500)
        assert c.maxsize == 500
