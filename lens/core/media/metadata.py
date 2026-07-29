from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lens.core.mount import MountBackend


# ---------------------------------------------------------------------------
# Extension → media type mapping (mirrors lens.core.commands.attach)
# ---------------------------------------------------------------------------

_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
_VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".avi"})
_AUDIO_EXTS = frozenset({".mp3", ".wav"})
_DOCUMENT_EXTS = frozenset({".pdf", ".txt", ".md"})


def _derive_media_type(ext: str) -> str:
    ext_lower = ext.lower()
    if ext_lower in _IMAGE_EXTS:
        return "image"
    if ext_lower in _VIDEO_EXTS:
        return "video"
    if ext_lower in _AUDIO_EXTS:
        return "audio"
    if ext_lower in _DOCUMENT_EXTS:
        return "document"
    return "other"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    """Metadata for a single media file on the mount.

    The first four fields are always derived from the file path and backend
    info (read-only / reserved).  Everything from the sidecar YAML lives in
    ``extra`` so the dict is flat when serialised.
    """

    relative_path: str
    name: str
    extension: str
    type: str
    extra: dict[str, Any] = field(default_factory=lambda: {})  # pyright: ignore[reportUnknownVariableType]

    def flattened(self) -> dict[str, Any]:
        """Return a flat dict with guaranteed keys + all ``extra`` entries.

        The result is suitable for JSON serialisation.
        """
        d: dict[str, Any] = {
            "relative_path": self.relative_path,
            "name": self.name,
            "extension": self.extension,
            "type": self.type,
        }
        d.update(self.extra)
        return d

    def composite_role(self) -> str | None:
        """Return ``"foreground"``/``"background"`` if the ``composite`` sidecar key is set, else ``None``."""
        value = self.extra.get("composite")
        if isinstance(value, str) and value.strip().lower() in ("foreground", "background"):
            return value.strip().lower()
        return None


# ---------------------------------------------------------------------------
# Path-based metadata resolver (no sidecar)
# ---------------------------------------------------------------------------


def resolve_path_metadata(
    relative_path: str,
    file_info: tuple[int, str] | None = None,
) -> MediaMetadata:
    """Build ``MediaMetadata`` from the path and optional backend info only.

    No sidecar file is read — the ``extra`` dict will be empty.
    """
    clean = relative_path.replace("\\", "/").lstrip("/")
    name = Path(clean).name
    ext = Path(name).suffix.lower()
    mtype = _derive_media_type(ext)

    return MediaMetadata(
        relative_path=clean,
        name=name,
        extension=ext,
        type=mtype,
        extra={},
    )


# ---------------------------------------------------------------------------
# Sidecar store
# ---------------------------------------------------------------------------


_SIDECAR_EXT = ".yml"


def _sidecar_path(relative_path: str) -> str:
    """Return the mount-relative sidecar path for a media file.

    ``amy/house/couch.jpg`` → ``amy/house/couch.jpg.yml``
    """
    return relative_path.rstrip("/") + _SIDECAR_EXT


def _entry_is_sidecar(entries: list[dict[str, Any]], entry_name: str) -> bool:
    """Return ``True`` if *entry_name* looks like a sidecar for an entry in *entries*."""
    if not entry_name.endswith(_SIDECAR_EXT):
        return False
    base = entry_name[: -len(_SIDECAR_EXT)]
    return any(e["name"] == base for e in entries)


def filter_sidecars(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove sidecar ``.yml`` entries from a directory listing."""
    return [e for e in entries if not _entry_is_sidecar(entries, e["name"])]


class MediaStore:
    """CRUD for sidecar YAML files alongside media on a ``MountBackend``.

    A sidecar file lives at ``{media_path}.yml`` on the same backend.
    """

    def __init__(self, backend: MountBackend) -> None:
        self._backend = backend

    def load_sidecar(self, relative_path: str) -> dict[str, Any]:
        """Read and parse the sidecar YAML for *relative_path*.

        Returns an empty dict if no sidecar exists.
        """
        sp = _sidecar_path(relative_path)
        stream = self._backend.stream_file(sp)
        if stream is None:
            return {}
        data_bytes = b"".join(stream[0])
        parsed = yaml.safe_load(data_bytes)
        if not isinstance(parsed, dict):
            return {}
        return dict(parsed)  # pyright: ignore[reportUnknownArgumentType]

    def save_sidecar(self, relative_path: str, data: dict[str, Any]) -> None:
        """Write *data* as YAML to the sidecar file, replacing existing content."""
        sp = _sidecar_path(relative_path)
        dir_path = "/".join(sp.split("/")[:-1]) if "/" in sp else ""
        # put_file expects a dir and filename; split path.
        name = sp.split("/")[-1]
        yaml_bytes = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True).encode(
            "utf-8"
        )
        import io

        try:
            self._backend.put_file(dir_path, name, io.BytesIO(yaml_bytes))
        except FileExistsError:
            self._backend.delete(sp)
            self._backend.put_file(dir_path, name, io.BytesIO(yaml_bytes))

    def delete_sidecar(self, relative_path: str) -> None:
        """Delete the sidecar file for *relative_path*, if it exists."""
        sp = _sidecar_path(relative_path)
        try:
            self._backend.delete(sp)
        except FileNotFoundError:
            pass

    def get_metadata(self, relative_path: str) -> MediaMetadata:
        """Return full metadata (path-based + sidecar) for *relative_path*.

        The sidecar is loaded if present and its keys are merged into
        ``extra``.  The four reserved keys are never overwritten by the
        sidecar.

        Raises :exc:`FileNotFoundError` if the media file does not exist.
        """
        info = self._backend.get_file_info(relative_path)
        if info is None:
            raise FileNotFoundError(f"file not found: {relative_path}")
        meta = resolve_path_metadata(relative_path, file_info=info)
        sidecar = self.load_sidecar(relative_path)
        return MediaMetadata(
            relative_path=meta.relative_path,
            name=meta.name,
            extension=meta.extension,
            type=meta.type,
            extra=sidecar,
        )

    def update_metadata(self, relative_path: str, updates: dict[str, Any]) -> MediaMetadata:
        """Merge *updates* into the sidecar and return the new full metadata.

        Reserved keys (``relative_path``, ``name``, ``extension``, ``type``)
        in *updates* are silently ignored. If the merged result is empty,
        the sidecar is deleted (if present) instead of writing an empty file.
        """
        existing = self.load_sidecar(relative_path)
        reserved = {"relative_path", "name", "extension", "type"}
        for k, v in updates.items():
            if k not in reserved:
                existing[k] = v
        if existing:
            self.save_sidecar(relative_path, existing)
        else:
            self.delete_sidecar(relative_path)
        return self.get_metadata(relative_path)
