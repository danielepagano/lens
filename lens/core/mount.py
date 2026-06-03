"""Mount backend abstraction for media file storage.

Supports two backends selected by the ``mount_point`` value in ``lens.toml``:

- Local filesystem (default): ``mount_point = "media"`` or an absolute path.
- S3-compatible object storage: ``mount_point = "s3://bucket"`` or
  ``"s3://bucket/prefix"``.  Standard AWS environment variables are used
  (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, ``AWS_ENDPOINT_URL``,
  ``AWS_DEFAULT_REGION``).  Works with Cloudflare R2 and any S3-compatible
  service.
"""

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import mimetypes
import shutil
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Iterable

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class MountBackend(ABC):
    """Abstract backend for mount-point file operations."""

    @abstractmethod
    def list_dir(self, subpath: str) -> list[dict[str, Any]] | None:
        """Return ``[{name, is_dir}]`` entries at *subpath*, or ``None`` if not a directory."""

    @abstractmethod
    def stream_file(self, subpath: str) -> tuple[Iterable[bytes], str] | None:
        """Return ``(byte_stream, content_type)`` for *subpath*, or ``None`` if not found."""

    @abstractmethod
    def get_file_info(self, subpath: str) -> tuple[int, str] | None:
        """Return ``(size_bytes, content_type)`` for *subpath*, or ``None`` if not found."""

    @abstractmethod
    def stream_file_range(self, subpath: str, *, start: int | None, end: int | None) -> Iterable[bytes] | None:
        """Return a byte stream for a (possibly ranged) file read.

        Args:
            subpath: Mount-relative file path.
            start: 0-based start byte (inclusive) or None for start of file.
            end: 0-based end byte (inclusive) or None for end of file.

        Returns:
            An iterable of bytes or None if not found.
        """

    @abstractmethod
    def file_exists(self, subpath: str) -> bool:
        """Return ``True`` if a file exists at *subpath*."""

    @abstractmethod
    def put_file(self, dir_path: str, filename: str, data: BinaryIO) -> str:
        """Store *data* at ``dir_path/filename``.

        Returns the mount-relative path of the stored file.
        Raises :exc:`FileExistsError` if the destination already exists.
        """

    @abstractmethod
    def delete(self, subpath: str) -> str:
        """Delete the file or empty directory at *subpath*.

        Returns ``"file"`` or ``"dir"`` indicating what was deleted.
        Raises :exc:`FileNotFoundError` if *subpath* does not exist.
        Raises :exc:`OSError` if *subpath* is a non-empty directory.
        """

    @abstractmethod
    def move(self, src: str, dst: str) -> str:
        """Move/rename the file at *src* to *dst*.

        Returns the new mount-relative path.
        Raises :exc:`FileNotFoundError` if *src* does not exist.
        Raises :exc:`FileExistsError` if *dst* already exists.
        Raises :exc:`ValueError` if either path escapes the mount root.
        """

    @abstractmethod
    def delete_tree(self, subpath: str) -> None:
        """Delete the file or directory at *subpath* and all descendants.

        No-op if *subpath* does not exist. *subpath* must be non-empty after
        normalization (cannot delete the entire mount root).
        """

    @abstractmethod
    def move_tree(self, src: str, dst: str) -> None:
        """Move the file or directory *src* to *dst* recursively.

        No-op if *src* does not exist. Raises :exc:`FileExistsError` if *dst*
        exists. Source and destination must be non-empty after normalization.
        """


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".mp4", ".webm", ".mov", ".avi",
    ".pdf", ".txt", ".md",
    ".yaml", ".yml", ".json",
    ".mp3", ".wav"
})

_CHUNK = 65536


class LocalMountBackend(MountBackend):
    """Mount backend backed by a local filesystem directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, subpath: str) -> Path:
        full = (self._root / subpath.lstrip("/")).resolve()
        try:
            full.relative_to(self._root)
        except ValueError:
            raise ValueError("path escapes the mount directory")
        return full

    def list_dir(self, subpath: str) -> list[dict[str, Any]] | None:
        target = self._resolve(subpath)
        if not target.exists() or not target.is_dir():
            return None

        def _include(p: Path) -> bool:
            if p.name.startswith("."):
                return False
            if p.is_dir():
                return True
            return p.suffix.lower() in _SUPPORTED_EXTENSIONS

        entries = sorted(
            (p for p in target.iterdir() if _include(p)),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        return [{"name": e.name, "is_dir": e.is_dir()} for e in entries]

    def stream_file(self, subpath: str) -> tuple[Iterable[bytes], str] | None:
        full = self._resolve(subpath)
        if not full.exists() or not full.is_file():
            return None
        content_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
        try:
            file_obj = full.open("rb")
        except FileNotFoundError:
            return None

        def _gen() -> Iterable[bytes]:
            with file_obj as f:
                while chunk := f.read(_CHUNK):
                    yield chunk

        return _gen(), content_type

    def get_file_info(self, subpath: str) -> tuple[int, str] | None:
        full = self._resolve(subpath)
        if not full.exists() or not full.is_file():
            return None
        try:
            size = full.stat().st_size
        except FileNotFoundError:
            return None
        content_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
        return size, content_type

    def stream_file_range(self, subpath: str, *, start: int | None, end: int | None) -> Iterable[bytes] | None:
        full = self._resolve(subpath)
        if not full.exists() or not full.is_file():
            return None
        try:
            size = full.stat().st_size
        except FileNotFoundError:
            return None
        s = 0 if start is None else start
        e = (size - 1) if end is None else end
        if size <= 0 or s < 0 or s >= size or e < s:
            return None
        e = min(e, size - 1)
        remaining = e - s + 1
        try:
            file_obj = full.open("rb")
        except FileNotFoundError:
            return None
        file_obj.seek(s)

        def _gen() -> Iterable[bytes]:
            nonlocal remaining
            with file_obj as f:
                while remaining > 0:
                    chunk = f.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return _gen()

    def file_exists(self, subpath: str) -> bool:
        # ValueError from _resolve means path traversal — let it propagate.
        full = self._resolve(subpath)
        return full.exists() and full.is_file()

    def put_file(self, dir_path: str, filename: str, data: BinaryIO) -> str:
        target_dir = self._resolve(dir_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / Path(filename).name
        if dest.exists():
            rel = dir_path.rstrip("/") + "/" + Path(filename).name
            raise FileExistsError(f"file already exists: {rel}")
        with dest.open("wb") as f:
            shutil.copyfileobj(data, f)
        return str(dest.relative_to(self._root))

    def delete(self, subpath: str) -> str:
        full = self._resolve(subpath)
        if not full.exists():
            raise FileNotFoundError(f"not found: {subpath}")
        if full.is_dir():
            try:
                full.rmdir()
            except OSError:
                raise OSError("directory is not empty")
            return "dir"
        full.unlink()
        return "file"

    def move(self, src: str, dst: str) -> str:
        src_full = self._resolve(src)
        dst_full = self._resolve(dst)
        if not src_full.exists():
            raise FileNotFoundError(f"not found: {src}")
        if dst_full.exists():
            raise FileExistsError(f"file already exists: {dst}")
        dst_full.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_full), str(dst_full))
        return str(dst_full.relative_to(self._root))

    def delete_tree(self, subpath: str) -> None:
        clean = normalize_subpath(subpath)
        if not clean:
            raise ValueError("delete_tree requires a non-empty subpath")
        full = self._resolve(clean)
        if not full.exists():
            return
        if full.is_file():
            full.unlink()
            return
        shutil.rmtree(full)

    def move_tree(self, src: str, dst: str) -> None:
        clean_src = normalize_subpath(src)
        clean_dst = normalize_subpath(dst)
        if not clean_src or not clean_dst:
            raise ValueError("move_tree requires non-empty source and destination")
        src_full = self._resolve(clean_src)
        dst_full = self._resolve(clean_dst)
        if not src_full.exists():
            return
        if dst_full.exists():
            raise FileExistsError(f"destination already exists: {dst}")
        dst_full.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_full), str(dst_full))


# ---------------------------------------------------------------------------
# S3 backend
# ---------------------------------------------------------------------------


def normalize_subpath(subpath: str) -> str:
    """Collapse ``..`` and ``.`` in *subpath* without touching the filesystem.

    Returns a clean relative path (no leading/trailing slash, no ``..``).
    """
    parts: list[str] = []
    for part in subpath.replace("\\", "/").split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    return "/".join(parts)


class S3MountBackend(MountBackend):
    """Mount backend backed by an S3-compatible object store (e.g. Cloudflare R2)."""

    def __init__(self, bucket: str, prefix: str, s3_client: S3Client) -> None:
        """
        Args:
            bucket: S3 bucket name.
            prefix: Key prefix within the bucket (must end with ``"/"`` if non-empty,
                    or be an empty string).
            s3_client: A boto3 S3 client instance.
        """
        self.bucket = bucket
        self.prefix = prefix  # "" or "some/path/"
        self._s3 = s3_client

    def _key(self, subpath: str) -> str:
        return self.prefix + normalize_subpath(subpath)

    def _dir_prefix(self, subpath: str) -> str:
        """Return the S3 prefix for a directory listing."""
        clean = normalize_subpath(subpath)
        if clean:
            return self.prefix + clean + "/"
        return self.prefix  # root listing

    def list_dir(self, subpath: str) -> list[dict[str, Any]] | None:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        dir_prefix = self._dir_prefix(subpath)
        try:
            resp = self._s3.list_objects_v2(
                Bucket=self.bucket,
                Delimiter="/",
                Prefix=dir_prefix,
            )
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("NoSuchBucket", "404"):
                return None
            raise

        dirs: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []

        for cp in resp.get("CommonPrefixes") or []:
            raw_prefix: str = cp.get("Prefix", "")
            name = raw_prefix.rstrip("/").rsplit("/", 1)[-1]
            if not name.startswith("."):
                dirs.append({"name": name, "is_dir": True})

        for obj in resp.get("Contents") or []:
            key: str = obj.get("Key", "")
            name = key.rsplit("/", 1)[-1]
            if not name or name.startswith("."):
                continue
            ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
            if ext in _SUPPORTED_EXTENSIONS:
                files.append({"name": name, "is_dir": False})

        if not dirs and not files and normalize_subpath(subpath):
            return None

        dirs.sort(key=lambda e: e["name"].lower())
        files.sort(key=lambda e: e["name"].lower())
        return dirs + files

    def stream_file(self, subpath: str) -> tuple[Iterable[bytes], str] | None:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        key = self._key(subpath)
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("NoSuchKey", "404", "NoSuchBucket"):
                return None
            raise
        content_type: str = obj.get("ContentType") or mimetypes.guess_type(subpath)[0] or "application/octet-stream"
        body = obj["Body"]

        def _gen() -> Iterable[bytes]:
            # iter_chunks is available on StreamingBody; fall back to read()
            if hasattr(body, "iter_chunks"):
                yield from body.iter_chunks(_CHUNK)
            else:
                while True:
                    chunk = body.read(_CHUNK)
                    if not chunk:
                        break
                    yield chunk

        return _gen(), content_type

    def get_file_info(self, subpath: str) -> tuple[int, str] | None:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        key = self._key(subpath)
        try:
            head = self._s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("404", "NoSuchKey", "NoSuchBucket"):
                return None
            raise
        size = int(head.get("ContentLength") or 0)
        content_type: str = head.get("ContentType") or mimetypes.guess_type(subpath)[0] or "application/octet-stream"
        return size, content_type

    def stream_file_range(self, subpath: str, *, start: int | None, end: int | None) -> Iterable[bytes] | None:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        key = self._key(subpath)
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if start is not None or end is not None:
            s = 0 if start is None else start
            if end is None:
                params["Range"] = f"bytes={s}-"
            else:
                params["Range"] = f"bytes={s}-{end}"
        try:
            obj = self._s3.get_object(**params)
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("NoSuchKey", "404", "NoSuchBucket"):
                return None
            raise

        body = obj["Body"]

        def _gen() -> Iterable[bytes]:
            if hasattr(body, "iter_chunks"):
                yield from body.iter_chunks(_CHUNK)
            else:
                while True:
                    chunk = body.read(_CHUNK)
                    if not chunk:
                        break
                    yield chunk

        return _gen()

    def file_exists(self, subpath: str) -> bool:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        key = self._key(subpath)
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("404", "NoSuchKey"):
                return False
            raise

    def put_file(self, dir_path: str, filename: str, data: BinaryIO) -> str:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        clean_dir = normalize_subpath(dir_path)
        clean_name = Path(filename).name
        rel_path = (clean_dir + "/" + clean_name).lstrip("/")
        key = self.prefix + rel_path
        # Check for existing object
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            raise FileExistsError(f"file already exists: {rel_path}")
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code not in ("404", "NoSuchKey"):
                raise
        content_type = mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data.read(), ContentType=content_type)
        return rel_path

    def delete(self, subpath: str) -> str:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        key = self._key(subpath)
        # Try to delete as a file
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            self._s3.delete_object(Bucket=self.bucket, Key=key)
            return "file"
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code not in ("404", "NoSuchKey"):
                raise

        # Not a file — check if it's a non-empty "directory"
        dir_prefix = self._dir_prefix(subpath)
        resp = self._s3.list_objects_v2(
            Bucket=self.bucket, Prefix=dir_prefix, MaxKeys=1
        )
        if resp.get("Contents") or resp.get("CommonPrefixes"):
            raise OSError("directory is not empty")

        # Empty or non-existent prefix
        if not normalize_subpath(subpath):
            raise FileNotFoundError(f"not found: {subpath}")
        return "dir"

    def move(self, src: str, dst: str) -> str:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        src_key = self._key(src)
        dst_clean = normalize_subpath(dst)
        dst_key = self.prefix + dst_clean

        # Verify src exists
        try:
            self._s3.head_object(Bucket=self.bucket, Key=src_key)
        except ClientError as e:
            code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"not found: {src}")
            raise

        # Verify dst does not exist
        try:
            self._s3.head_object(Bucket=self.bucket, Key=dst_key)
            raise FileExistsError(f"file already exists: {dst}")
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
            if code not in ("404", "NoSuchKey"):
                raise

        self._s3.copy_object(
            CopySource={"Bucket": self.bucket, "Key": src_key},
            Bucket=self.bucket,
            Key=dst_key,
        )
        self._s3.delete_object(Bucket=self.bucket, Key=src_key)
        return dst_clean

    def _iter_tree_keys(self, clean_subpath: str) -> list[str]:
        """Keys under *clean_subpath* (file at exact key or prefix + ``/``)."""
        base_key = self._key(clean_subpath)
        out: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=base_key):
            for obj in page.get("Contents") or []:
                k: str = obj.get("Key", "")
                if k == base_key or k.startswith(base_key + "/"):
                    out.append(k)
        return out

    def delete_tree(self, subpath: str) -> None:

        clean = normalize_subpath(subpath)
        if not clean:
            raise ValueError("delete_tree requires a non-empty subpath")
        keys = self._iter_tree_keys(clean)
        if not keys:
            return
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            self._s3.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )

    def move_tree(self, src: str, dst: str) -> None:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        clean_src = normalize_subpath(src)
        clean_dst = normalize_subpath(dst)
        if not clean_src or not clean_dst:
            raise ValueError("move_tree requires non-empty source and destination")
        src_base = self._key(clean_src)
        dst_base = self._key(clean_dst)
        keys = self._iter_tree_keys(clean_src)
        if not keys:
            return

        dst_keys: list[str] = []
        for sk in keys:
            if sk == src_base:
                dst_keys.append(dst_base)
            else:
                dst_keys.append(dst_base + sk[len(src_base) :])

        for dk in dst_keys:
            try:
                self._s3.head_object(Bucket=self.bucket, Key=dk)
                raise FileExistsError(f"destination already exists: {dk}")
            except ClientError as e:
                code: str = (e.response.get("Error") or {}).get("Code", "")  # type: ignore[union-attr]
                if code not in ("404", "NoSuchKey"):
                    raise

        for sk, dk in zip(keys, dst_keys, strict=True):
            self._s3.copy_object(
                Bucket=self.bucket,
                Key=dk,
                CopySource={"Bucket": self.bucket, "Key": sk},
            )
            self._s3.delete_object(Bucket=self.bucket, Key=sk)

    def presign_get_object(self, subpath: str, *, expires_in: int) -> str:
        """Return a time-limited HTTPS URL for ``GET`` on *subpath* (private object)."""
        key = self._key(subpath)
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_backend_from_uri(uri: str) -> S3MountBackend:
    """Create an :class:`S3MountBackend` from an ``s3://`` URI.

    Credentials and endpoint are read from the standard AWS environment
    variables (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
    ``AWS_ENDPOINT_URL``, ``AWS_DEFAULT_REGION``).
    """
    import boto3  # type: ignore[import-untyped]  # lazy import

    parsed = urllib.parse.urlparse(uri)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    s3: S3Client = boto3.client("s3")  # type: ignore[assignment]
    return S3MountBackend(bucket, prefix, s3)
