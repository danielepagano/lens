"""Unit tests for MediaCache (LRU, size-bound) and MediaSearchIndex."""

from __future__ import annotations

import threading

from lens.core.media.cache import MediaCache, MediaSearchIndex


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

    def test_warmed_defaults_false(self) -> None:
        c = MediaCache(maxsize=10)
        assert c.warmed is False

    def test_invalidate_all_resets_warmed(self) -> None:
        c = MediaCache(maxsize=10)
        c.warmed = True
        c.invalidate_all()
        assert c.warmed is False

    def test_ensure_capacity_raises_maxsize_when_smaller(self) -> None:
        c = MediaCache(maxsize=10)
        c.ensure_capacity(50)
        assert c.maxsize == 50

    def test_ensure_capacity_is_noop_when_already_larger(self) -> None:
        c = MediaCache(maxsize=100)
        c.ensure_capacity(10)
        assert c.maxsize == 100

    def test_claim_warm_first_caller_wins_then_stays_claimed(self) -> None:
        c = MediaCache(maxsize=10)
        assert c.claim_warm() is True
        assert c.warmed is True
        assert c.claim_warm() is False
        assert c.claim_warm() is False

    def test_claim_warm_can_be_reclaimed_after_invalidate_all(self) -> None:
        c = MediaCache(maxsize=10)
        assert c.claim_warm() is True
        c.invalidate_all()
        assert c.claim_warm() is True

    def test_has_a_search_index(self) -> None:
        c = MediaCache(maxsize=10)
        assert isinstance(c.search_index, MediaSearchIndex)

    def test_search_index_limit_is_configurable(self) -> None:
        c = MediaCache(maxsize=10, search_index_limit=3)
        assert c.search_index.limit == 3

    def test_invalidate_all_clears_search_index(self) -> None:
        c = MediaCache(maxsize=10)
        c.search_index.set("a.jpg", {"relative_path": "a.jpg"})
        c.invalidate_all()
        assert len(c.search_index) == 0
        assert c.search_index.locked is False


class TestMediaSearchIndex:
    def test_set_and_get(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.set("a.jpg", {"relative_path": "a.jpg", "name": "a.jpg"})
        record = idx.get("a.jpg")
        assert record is not None
        assert record.flattened["name"] == "a.jpg"

    def test_get_missing_returns_none(self) -> None:
        idx = MediaSearchIndex(limit=10)
        assert idx.get("nope") is None

    def test_remove(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.remove("a.jpg")
        assert idx.get("a.jpg") is None
        assert len(idx) == 0

    def test_remove_missing_does_not_raise(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.remove("nope")

    def test_rename_carries_over_extra_derived_fields(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.set("old.jpg", {"relative_path": "old.jpg", "name": "old.jpg", "character": "amy"})
        idx.rename("old.jpg", "new.jpg", {"relative_path": "new.jpg", "name": "new.jpg"})
        assert idx.get("old.jpg") is None
        record = idx.get("new.jpg")
        assert record is not None
        assert record.flattened["character"] == "amy"
        assert record.flattened["name"] == "new.jpg"

    def test_rename_missing_source_is_noop(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.rename("nope.jpg", "new.jpg", {"relative_path": "new.jpg"})
        assert len(idx) == 0

    def test_set_within_limit_stays_unlocked(self) -> None:
        idx = MediaSearchIndex(limit=2)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.set("b.jpg", {"relative_path": "b.jpg"})
        assert idx.locked is False
        assert len(idx) == 2

    def test_set_replacing_existing_key_does_not_count_against_limit(self) -> None:
        idx = MediaSearchIndex(limit=1)
        idx.set("a.jpg", {"relative_path": "a.jpg", "v": 1})
        idx.set("a.jpg", {"relative_path": "a.jpg", "v": 2})
        assert idx.locked is False
        record = idx.get("a.jpg")
        assert record is not None
        assert record.flattened["v"] == 2

    def test_exceeding_limit_locks_and_clears(self) -> None:
        idx = MediaSearchIndex(limit=2)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.set("b.jpg", {"relative_path": "b.jpg"})
        idx.set("c.jpg", {"relative_path": "c.jpg"})
        assert idx.locked is True
        assert len(idx) == 0

    def test_locked_index_ignores_further_writes(self) -> None:
        idx = MediaSearchIndex(limit=1)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.set("b.jpg", {"relative_path": "b.jpg"})  # locks
        assert idx.locked is True
        idx.set("c.jpg", {"relative_path": "c.jpg"})
        idx.remove("a.jpg")
        idx.rename("a.jpg", "z.jpg", {"relative_path": "z.jpg"})
        assert idx.locked is True
        assert idx.items() == []
        assert idx.get("a.jpg") is None

    def test_begin_bulk_load_within_limit_unlocks_and_clears(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        assert idx.begin_bulk_load(5) is True
        assert idx.locked is False
        assert len(idx) == 0  # caller repopulates after this

    def test_begin_bulk_load_over_limit_locks(self) -> None:
        idx = MediaSearchIndex(limit=5)
        assert idx.begin_bulk_load(6) is False
        assert idx.locked is True

    def test_clear_unlocks(self) -> None:
        idx = MediaSearchIndex(limit=1)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.set("b.jpg", {"relative_path": "b.jpg"})  # locks
        assert idx.locked is True
        idx.clear()
        assert idx.locked is False
        assert len(idx) == 0

    def test_items_empty_while_locked(self) -> None:
        idx = MediaSearchIndex(limit=1)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        idx.set("b.jpg", {"relative_path": "b.jpg"})
        assert idx.items() == []

    def test_contains(self) -> None:
        idx = MediaSearchIndex(limit=10)
        idx.set("a.jpg", {"relative_path": "a.jpg"})
        assert "a.jpg" in idx
        assert "b.jpg" not in idx


class TestMediaCacheConcurrency:
    """Regression coverage for the fact that this cache is genuinely shared
    across real OS threads (FastAPI dispatches sync route handlers onto a
    thread pool) rather than being a single-request, single-thread object."""

    def test_concurrent_set_and_invalidate_prefix_does_not_raise(self) -> None:
        c = MediaCache(maxsize=10_000)
        errors: list[BaseException] = []

        def writer(tid: int) -> None:
            try:
                for i in range(500):
                    c.set(f"list:{tid}:{i}", i)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        def invalidator() -> None:
            try:
                for _ in range(500):
                    c.invalidate_prefix("list:")
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(6)]
        threads += [threading.Thread(target=invalidator) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_claim_warm_only_one_thread_wins_under_a_real_race(self) -> None:
        c = MediaCache(maxsize=10)
        results: list[bool] = []
        results_lock = threading.Lock()

        def attempt() -> None:
            won = c.claim_warm()
            with results_lock:
                results.append(won)

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 19
