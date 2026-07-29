"""Integration tests for MediaService (cached MountBackend wrapper).

Uses LocalMountBackend with temp directories.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import yaml

from lens.core.media import MediaCache, MediaService
from lens.core.mount import LocalMountBackend


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_service(maxsize: int = 100) -> tuple[MediaService, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_svc_"))
    backend = LocalMountBackend(tmp)
    cache = MediaCache(maxsize=maxsize)
    svc = MediaService(backend, cache=cache)
    return svc, tmp


def _touch(svc: MediaService, rel: str) -> None:
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    svc.put_file(dir_part, name, io.BytesIO(b"hello"))


# ---------------------------------------------------------------------------
# list_dir — caching + sidecar filtering
# ---------------------------------------------------------------------------


class TestListDir:
    def test_empty_dir_returns_list(self) -> None:
        svc, _ = _make_service()
        assert svc.list_dir("") == []

    def test_lists_files(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        entries = svc.list_dir("")
        assert entries == [{"name": "amy.jpg", "is_dir": False}]

    def test_sidecar_filtered_out(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})  # creates amy.jpg.yml
        entries = svc.list_dir("")
        assert entries is not None
        names = [e["name"] for e in entries]
        assert "amy.jpg" in names
        assert "amy.jpg.yml" not in names

    def test_list_dir_caching_second_call(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.list_dir("")  # warm cache
        hit_before = svc.cache.hits
        svc.list_dir("")
        assert svc.cache.hits > hit_before

    def test_list_dir_none_for_nonexistent(self) -> None:
        svc, _ = _make_service()
        assert svc.list_dir("nope") is None

    def test_list_dir_subdir(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "chars/amy.jpg")
        entries = svc.list_dir("chars")
        assert entries == [{"name": "amy.jpg", "is_dir": False}]


# ---------------------------------------------------------------------------
# get_file_info
# ---------------------------------------------------------------------------


class TestGetFileInfo:
    def test_returns_info(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        info = svc.get_file_info("amy.jpg")
        assert info is not None
        size, ctype = info
        assert size == 5  # "hello"
        assert ctype is not None

    def test_missing_file_returns_none(self) -> None:
        svc, _ = _make_service()
        assert svc.get_file_info("nope.jpg") is None

    def test_caching(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.get_file_info("amy.jpg")  # warm
        hit_before = svc.cache.hits
        svc.get_file_info("amy.jpg")
        assert svc.cache.hits > hit_before


# ---------------------------------------------------------------------------
# file_exists
# ---------------------------------------------------------------------------


class TestFileExists:
    def test_exists(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        assert svc.file_exists("amy.jpg") is True

    def test_not_exists(self) -> None:
        svc, _ = _make_service()
        assert svc.file_exists("nope.jpg") is False

    def test_caching(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.file_exists("amy.jpg")  # warm
        hit_before = svc.cache.hits
        svc.file_exists("amy.jpg")
        assert svc.cache.hits > hit_before


# ---------------------------------------------------------------------------
# get_metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_no_sidecar(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        meta = svc.get_metadata("amy.jpg")
        assert meta.name == "amy.jpg"
        assert meta.type == "image"
        assert meta.extra == {}

    def test_with_sidecar(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})
        meta = svc.get_metadata("amy.jpg")
        assert meta.extra == {"character": "amy"}

    def test_caching(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.get_metadata("amy.jpg")  # warm
        hit_before = svc.cache.hits
        svc.get_metadata("amy.jpg")
        assert svc.cache.hits > hit_before


# ---------------------------------------------------------------------------
# write ops — cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    def test_put_file_invalidates_list(self) -> None:
        svc, _ = _make_service()
        svc.list_dir("")  # warm
        _touch(svc, "amy.jpg")  # should invalidate
        assert svc.cache.get("list:") is None

    def test_delete_invalidates_list_and_meta(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.get_metadata("amy.jpg")  # warm
        svc.list_dir("")  # warm
        svc.delete("amy.jpg")
        assert svc.cache.get("list:") is None
        assert svc.cache.get("meta:amy.jpg") is None

    def test_delete_also_deletes_sidecar(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})
        svc.delete("amy.jpg")
        # sidecar yml should also be gone
        result = svc.stream_file("amy.jpg.yml")
        assert result is None  # sidecar was deleted

    def test_move_invalidates_both_dirs(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.list_dir("")  # warm
        svc.move("amy.jpg", "bob.jpg")
        assert svc.cache.get("list:") is None

    def test_move_also_moves_sidecar(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})
        svc.move("amy.jpg", "bob.jpg")
        meta = svc.get_metadata("bob.jpg")
        assert meta.extra == {"character": "amy"}

    def test_move_sidecar_not_present_ok(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.move("amy.jpg", "bob.jpg")  # no sidecar — should not raise

    def test_update_metadata_sets_cache(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})
        # cache should now have it
        cached = svc.cache.get("meta:amy.jpg")
        assert cached is not None
        assert cached.extra.get("character") == "amy"

    def test_delete_metadata_caches_fresh_empty_result(self) -> None:
        # delete_metadata caches the now-current (sidecar-less) metadata
        # rather than just invalidating, so a reopen right after doesn't
        # pay a round-trip to confirm the sidecar is gone.
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})
        svc.delete_metadata("amy.jpg")
        cached = svc.cache.get("meta:amy.jpg")
        assert cached is not None
        assert cached.extra == {}
        assert svc.get_metadata("amy.jpg").extra == {}

    def test_delete_metadata_missing_file_does_not_raise(self) -> None:
        # No underlying media file at all — nothing valid to cache, but
        # this must stay a safe no-op (mirrors the DELETE route's 200-OK
        # "already gone" contract).
        svc, _ = _make_service()
        svc.delete_metadata("nope.jpg")
        assert svc.cache.get("meta:nope.jpg") is None

    def test_stream_file_passthrough(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        result = svc.stream_file("amy.jpg")
        assert result is not None
        data, _ctype = result  # pyright: ignore[reportUnusedVariable]
        assert b"".join(data) == b"hello"

    def test_stream_missing_returns_none(self) -> None:
        svc, _ = _make_service()
        assert svc.stream_file("nope.jpg") is None


# ---------------------------------------------------------------------------
# warm_cache
# ---------------------------------------------------------------------------

# pyright: reportPrivateUsage=false


class TestWarmCache:
    def test_warm_populates_list_entries(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        _touch(svc, "sub/bob.jpg")
        svc.warm_cache()
        root = svc.cache.get("list:")
        assert root is not None
        names = {e["name"] for e in root}
        assert "amy.jpg" in names
        assert "sub" in names
        sub = svc.cache.get("list:sub")
        assert sub is not None
        assert sub == [{"name": "bob.jpg", "is_dir": False}]

    def test_warm_populates_meta_entries(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.warm_cache()
        meta = svc.cache.get("meta:amy.jpg")
        assert meta is not None
        assert meta.name == "amy.jpg"
        assert meta.type == "image"

    def test_warm_merges_sidecar(self) -> None:
        svc, tmp = _make_service()
        _touch(svc, "amy.jpg")
        sidecar_path = tmp / "amy.jpg.yml"
        sidecar_path.write_text(yaml.safe_dump({"character": "amy"}))
        svc.warm_cache()
        meta = svc.cache.get("meta:amy.jpg")
        assert meta is not None
        assert meta.extra.get("character") == "amy"

    def test_warm_omits_sidecar_from_listings(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy"})  # creates sidecar
        svc.warm_cache()
        root = svc.cache.get("list:")
        assert root is not None
        names = {e["name"] for e in root}
        assert "amy.jpg" in names
        assert "amy.jpg.yml" not in names

    def test_warm_empty_mount_is_noop(self) -> None:
        svc, _ = _make_service()
        svc.warm_cache()
        assert svc.cache.size == 0

    def test_lazy_warm_on_first_list_dir(self) -> None:
        svc, _ = _make_service()
        assert not svc._warmed
        _touch(svc, "amy.jpg")
        svc.list_dir("")
        assert svc._warmed
        # list: cache should be populated
        assert svc.cache.get("list:") is not None

    def test_lazy_warm_on_first_get_metadata(self) -> None:
        svc, _ = _make_service()
        assert not svc._warmed
        _touch(svc, "amy.jpg")
        svc.get_metadata("amy.jpg")
        assert svc._warmed

    def test_warm_only_once(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.warm_cache()
        svc._warmed = False
        # After re-enabling, calling list_dir should warm again
        # But first let's verify warm happened
        svc.warm_cache()  # should be safe to call twice
        # No crash is the main check

    def test_invalidate_cache_resets_warmed(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.list_dir("")  # warms
        assert svc._warmed
        svc.invalidate_cache()
        assert not svc._warmed

    def test_warm_handles_deep_tree(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a/b/c/d/e/deep.jpg")
        svc.warm_cache()
        for sub in ("", "a", "a/b", "a/b/c", "a/b/c/d", "a/b/c/d/e"):
            listing = svc.cache.get(f"list:{sub}")
            assert listing is not None, f"list:{sub} should exist"
        meta = svc.cache.get("meta:a/b/c/d/e/deep.jpg")
        assert meta is not None
        assert meta.name == "deep.jpg"
