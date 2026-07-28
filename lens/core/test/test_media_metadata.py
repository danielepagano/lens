"""Unit tests for MediaMetadata, resolve_path_metadata, and sidecar helpers."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path


# pyright: reportPrivateUsage=false

from lens.core.media.metadata import (
    MediaMetadata,
    MediaStore,
    _derive_media_type,
    _entry_is_sidecar,
    _sidecar_path,
    filter_sidecars,
    resolve_path_metadata,
)
from lens.core.mount import LocalMountBackend


# ---------------------------------------------------------------------------
# Helper: create a local backend rooted at a temp dir
# ---------------------------------------------------------------------------


def _make_backend() -> LocalMountBackend:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_meta_"))
    return LocalMountBackend(tmp)


def _touch(backend: LocalMountBackend, rel: str) -> None:
    """Create an empty file on the mount at *rel*."""
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    backend.put_file(dir_part, name, io.BytesIO(b""))


# ---------------------------------------------------------------------------
# derive_media_type
# ---------------------------------------------------------------------------


class TestDeriveMediaType:
    def test_image_extensions(self) -> None:
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            assert _derive_media_type(ext) == "image"

    def test_video_extensions(self) -> None:
        for ext in (".mp4", ".webm", ".mov", ".avi"):
            assert _derive_media_type(ext) == "video"

    def test_audio_extensions(self) -> None:
        for ext in (".mp3", ".wav"):
            assert _derive_media_type(ext) == "audio"

    def test_document_extensions(self) -> None:
        for ext in (".pdf", ".txt", ".md"):
            assert _derive_media_type(ext) == "document"

    def test_other_extension(self) -> None:
        assert _derive_media_type(".bin") == "other"
        assert _derive_media_type(".json") == "other"
        assert _derive_media_type(".yml") == "other"

    def test_case_insensitive(self) -> None:
        assert _derive_media_type(".JPG") == "image"


# ---------------------------------------------------------------------------
# resolve_path_metadata
# ---------------------------------------------------------------------------


class TestResolvePathMetadata:
    def test_simple_path(self) -> None:
        meta = resolve_path_metadata("amy/house/couch.jpg")
        assert meta.relative_path == "amy/house/couch.jpg"
        assert meta.name == "couch.jpg"
        assert meta.extension == ".jpg"
        assert meta.type == "image"

    def test_path_with_leading_slash(self) -> None:
        meta = resolve_path_metadata("/amy/house/couch.jpg")
        assert meta.relative_path == "amy/house/couch.jpg"
        assert meta.name == "couch.jpg"

    def test_path_with_backslashes(self) -> None:
        meta = resolve_path_metadata("amy\\house\\couch.jpg")
        assert meta.relative_path == "amy/house/couch.jpg"
        assert meta.name == "couch.jpg"

    def test_video_path(self) -> None:
        meta = resolve_path_metadata("scenes/action.mp4")
        assert meta.name == "action.mp4"
        assert meta.extension == ".mp4"
        assert meta.type == "video"

    def test_audio_path(self) -> None:
        meta = resolve_path_metadata("music/bg.mp3")
        assert meta.type == "audio"

    def test_document_path(self) -> None:
        meta = resolve_path_metadata("notes/reference.pdf")
        assert meta.type == "document"

    def test_unknown_extension(self) -> None:
        meta = resolve_path_metadata("data.bin")
        assert meta.type == "other"

    def test_empty_extra_by_default(self) -> None:
        meta = resolve_path_metadata("file.jpg")
        assert meta.extra == {}

    def test_flattened(self) -> None:
        meta = resolve_path_metadata("test.jpg")
        flat = meta.flattened()
        assert flat["relative_path"] == "test.jpg"
        assert flat["name"] == "test.jpg"
        assert flat["extension"] == ".jpg"
        assert flat["type"] == "image"

    def test_flattened_includes_extra(self) -> None:
        meta = MediaMetadata(
            relative_path="test.jpg",
            name="test.jpg",
            extension=".jpg",
            type="image",
            extra={"character": "amy", "tags": ["portrait"]},
        )
        flat = meta.flattened()
        assert flat["character"] == "amy"
        assert flat["tags"] == ["portrait"]


# ---------------------------------------------------------------------------
# _sidecar_path and sidecar filtering
# ---------------------------------------------------------------------------


class TestSidecarPath:
    def test_sidecar_path(self) -> None:
        assert _sidecar_path("amy.jpg") == "amy.jpg.yml"
        assert _sidecar_path("amy/house/couch.jpg") == "amy/house/couch.jpg.yml"
        assert _sidecar_path("/leading/slash.png") == "/leading/slash.png.yml"


class TestEntryIsSidecar:
    def test_no_base_file(self) -> None:
        entries = [{"name": "foo.jpg", "is_dir": False}]
        assert _entry_is_sidecar(entries, "foo.jpg.yml") is True
        assert _entry_is_sidecar(entries, "bar.jpg.yml") is False

    def test_not_yml(self) -> None:
        entries = [{"name": "foo.jpg", "is_dir": False}]
        assert _entry_is_sidecar(entries, "foo.jpg") is False


class TestFilterSidecars:
    def test_filters_sidecars(self) -> None:
        entries = [
            {"name": "amy.jpg", "is_dir": False},
            {"name": "amy.jpg.yml", "is_dir": False},
            {"name": "house.png", "is_dir": False},
        ]
        result = filter_sidecars(entries)
        assert len(result) == 2
        assert result[0]["name"] == "amy.jpg"
        assert result[1]["name"] == "house.png"

    def test_no_sidecars(self) -> None:
        entries = [{"name": "a.jpg", "is_dir": False}, {"name": "b.png", "is_dir": False}]
        assert filter_sidecars(entries) == entries

    def test_orphan_yml_passes_through(self) -> None:
        entries = [{"name": "data.yml", "is_dir": False}]
        assert filter_sidecars(entries) == entries


# ---------------------------------------------------------------------------
# MediaStore integration tests
# ---------------------------------------------------------------------------


class TestMediaStore:
    def test_load_sidecar_nonexistent(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        assert store.load_sidecar("amy.jpg") == {}

    def test_save_and_load_sidecar(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy", "expression": "happy"})
        loaded = store.load_sidecar("amy.jpg")
        assert loaded == {"character": "amy", "expression": "happy"}

    def test_save_overwrites_existing(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy"})
        store.save_sidecar("amy.jpg", {"character": "bob"})
        loaded = store.load_sidecar("amy.jpg")
        assert loaded == {"character": "bob"}

    def test_delete_sidecar(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy"})
        store.delete_sidecar("amy.jpg")
        assert store.load_sidecar("amy.jpg") == {}

    def test_delete_missing_sidecar_does_not_raise(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.delete_sidecar("amy.jpg")  # no sidecar exists

    def test_get_metadata_no_sidecar(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        meta = store.get_metadata("amy.jpg")
        assert meta.name == "amy.jpg"
        assert meta.type == "image"
        assert meta.extra == {}

    def test_get_metadata_with_sidecar(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy", "tags": ["portrait"]})
        meta = store.get_metadata("amy.jpg")
        assert meta.name == "amy.jpg"
        assert meta.extra == {"character": "amy", "tags": ["portrait"]}

    def test_update_metadata_creates_sidecar(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        meta = store.update_metadata("amy.jpg", {"character": "amy"})
        assert meta.extra == {"character": "amy"}

    def test_update_metadata_merges(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy"})
        meta = store.update_metadata("amy.jpg", {"expression": "happy"})
        assert meta.extra == {"character": "amy", "expression": "happy"}

    def test_update_metadata_overwrites_key(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        store.save_sidecar("amy.jpg", {"character": "amy"})
        meta = store.update_metadata("amy.jpg", {"character": "bob"})
        assert meta.extra == {"character": "bob"}

    def test_update_metadata_ignores_reserved_keys(self) -> None:
        backend = _make_backend()
        _touch(backend, "amy.jpg")
        store = MediaStore(backend)
        meta = store.update_metadata("amy.jpg", {"name": "evil-name", "type": "video", "extra_data": "ok"})
        assert meta.name == "amy.jpg"  # not overwritten
        assert meta.type == "image"  # not overwritten
        assert meta.extra == {"extra_data": "ok"}
