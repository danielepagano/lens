"""Core implementation of the ``media generate`` command.

Resolves an ``[[image]]`` backend, validates and `@`-expands the prompt,
streams the backend's events to completion, then writes each returned image
plus a per-batch sidecar to the mount under ``generated/<slug>/``.

CLI / SSE share this core: the CLI consumes the iterator end-to-end, while the
server route can stream the same events out as SSE and persist on explicit
saves.
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from typing import Any, cast

import yaml

from lens.core.prompt_transforms import (
    PromptTransformContext,
    PromptTransformTarget,
    transform_prompt,
)
from lens.core.exceptions import LensException
from lens.core.image import registry as image_registry
from lens.core.image.backend import ImageBackend
from lens.core.image.spec import (
    Done,
    Error,
    ImageDescriptor,
    ImageSpec,
    ItemReady,
    Progress,
)
from lens.core.media_presign import (
    DEFAULT_MEDIA_PRESIGN_TTL_SECONDS,
    presign_mount_read_urls,
)
from lens.core.mount import MountBackend
from lens.core.operators.session import prompt_to_slug
from lens.core.project import (
    ProjectSession,
    get_mount_backend,
    get_mount_point,
)


@dataclass
class GenerateResult:
    """Outcome of a single ``media generate`` call."""

    slug: str
    batch_seq: int
    paths: list[str]
    sidecar_path: str
    prompt_resolved: str
    descriptor_id: str


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Resolved generation request (no I/O to mount except optional backend)."""

    descriptor: ImageDescriptor
    spec: ImageSpec
    slug: str
    session_dir: str
    prompt_raw: str
    prompt_resolved: str
    reference_paths: tuple[str, ...] = ()


@dataclass
class SavedItem:
    """Result of writing one image (and sidecar on first result in a batch)."""

    batch_seq: int
    result_seq: int
    path: str
    sidecar_path: str
    sidecar_created: bool


@dataclass(frozen=True)
class BatchSidecarParams:
    """Input fields stored in ``b_<n>.yaml`` for replay via ``--from``."""

    prompt: str
    negative_prompt: str | None
    aspect_ratio: str
    size: str
    batch_size: int
    model_id: str
    slug: str
    ref_paths: tuple[str, ...] = ()


_BATCH_SIDECAR_RE = re.compile(r"^b_(\d+)\.ya?ml$", re.IGNORECASE)
_SLUG_OK = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_aspect(descriptor: ImageDescriptor, aspect: str) -> str:
    if aspect not in descriptor.aspect_ratios:
        raise LensException(
            f"aspect {aspect!r} not allowed for image backend {descriptor.id!r} "
            f"(supported: {list(descriptor.aspect_ratios)})"
        )
    return aspect


def _validate_size(descriptor: ImageDescriptor, size: str) -> str:
    if size not in descriptor.sizes:
        raise LensException(
            f"size {size!r} not allowed for image backend {descriptor.id!r} "
            f"(supported: {list(descriptor.sizes)})"
        )
    return size


def _validate_batch(descriptor: ImageDescriptor, batch: int) -> int:
    if batch < 1:
        raise LensException(f"batch must be >= 1 (got {batch})")
    if batch > descriptor.max_batch:
        raise LensException(
            f"batch {batch} exceeds backend max_batch={descriptor.max_batch}"
        )
    return batch


def _validate_slug(slug: str) -> str:
    if not slug:
        raise LensException("slug is empty (after auto-deriving from prompt)")
    if not _SLUG_OK.match(slug):
        raise LensException(
            f"slug {slug!r} must match [A-Za-z0-9_-]+ "
            "(letters, digits, underscore, hyphen)"
        )
    return slug


def _enforce_prompt_length(text: str, *, limit: int, label: str) -> None:
    n = len(text)
    if n > limit:
        raise LensException(
            f"prompt too long ({label}): {n} > max_prompt_chars={limit}"
        )


def _resolve_prompt(prompt: str, session: ProjectSession) -> str:
    return transform_prompt(
        prompt,
        PromptTransformContext(
            project_root=session.project_root,
            storage=session.new_storage(),
        ),
        target=PromptTransformTarget.FLAT,
    )


def _next_batch_seq(backend: MountBackend, session_dir: str) -> int:
    entries = backend.list_dir(session_dir) or []
    max_seq = 0
    for entry in entries:
        if entry.get("is_dir"):
            continue
        match = _BATCH_SIDECAR_RE.match(str(entry.get("name", "")))
        if match is not None:
            seq = int(match.group(1))
            if seq > max_seq:
                max_seq = seq
    return max_seq + 1


def _next_result_seq_in_batch(
    backend: MountBackend, session_dir: str, batch_seq: int
) -> int:
    pat = re.compile(
        rf"^b_{re.escape(str(batch_seq))}_r_(\d+)\.[^.]+$", re.IGNORECASE
    )
    max_n = 0
    for entry in backend.list_dir(session_dir) or []:
        if entry.get("is_dir"):
            continue
        m = pat.match(str(entry.get("name", "")))
        if m is not None:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1


def _build_sidecar(
    *,
    spec: ImageSpec,
    descriptor: ImageDescriptor,
    prompt_raw: str,
    prompt_resolved: str,
    batch_seq: int,
    reference_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "batch": batch_seq,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_id": descriptor.id,
        "api": descriptor.api,
        "model": descriptor.model,
        "prompt": {
            "raw": prompt_raw,
            "resolved": prompt_resolved,
        },
        "negative_prompt": spec.negative_prompt,
        "aspect_ratio": spec.aspect_ratio,
        "size": spec.size,
        "batch_size": spec.batch,
    }
    if reference_paths:
        out["refs"] = list(reference_paths)
    return out


def _slug_from_sidecar_path(path: Path) -> str:
    parent = path.parent
    if parent.name and parent.parent.name == "generated":
        return parent.name
    return parent.name


def resolve_sidecar_path(project_root: Path, sidecar: Path | str) -> Path:
    """Resolve a batch sidecar to a filesystem path under the local mount only.

    Accepts a mount-relative path (same shape as printed after generate:
    ``generated/<slug>/b_<n>.yaml``) or an absolute path that still lies inside
    ``mount_point``. Remote mounts (``s3://``) are not supported for ``--from``.
    """
    mount_root = get_mount_point(project_root)
    if mount_root is None:
        raise LensException(
            "--from requires a local mount_point in lens.toml (not s3:// or unset)"
        )
    mount_resolved = mount_root.resolve()
    p = Path(sidecar).expanduser()
    if p.is_absolute():
        out = p.resolve()
        if not out.is_file():
            raise LensException(f"sidecar not found: {sidecar}")
        if not out.is_relative_to(mount_resolved):
            raise LensException(
                "sidecar must be under the configured mount; "
                "use a mount-relative path such as generated/<slug>/b_1.yaml"
            )
        return out
    cand = (mount_resolved / p).resolve()
    if not cand.is_file():
        raise LensException(
            f"sidecar not found: {sidecar} (under mount {mount_resolved})"
        )
    if not cand.is_relative_to(mount_resolved):
        raise LensException("sidecar path escapes mount root")
    return cand


def read_batch_sidecar(path: Path) -> BatchSidecarParams:
    """Load generation parameters from a ``b_<seq>.yaml`` sidecar file."""
    try:
        raw_yaml = path.read_text(encoding="utf-8")
    except OSError as e:
        raise LensException(f"cannot read sidecar: {e}") from e
    loaded = yaml.safe_load(raw_yaml)
    if not isinstance(loaded, dict):
        raise LensException("sidecar must be a YAML mapping")
    data = cast(dict[str, Any], loaded)

    pr = data.get("prompt")
    prompt_text: str | None
    if isinstance(pr, dict):
        pr_map = cast(dict[str, Any], pr)
        raw = pr_map.get("raw")
        prompt_text = raw if isinstance(raw, str) else None
        if prompt_text is None:
            resolved = pr_map.get("resolved")
            prompt_text = resolved if isinstance(resolved, str) else None
    elif isinstance(pr, str):
        prompt_text = pr
    else:
        prompt_text = None
    if not prompt_text:
        raise LensException("sidecar missing prompt (raw or resolved)")

    aspect = data.get("aspect_ratio")
    size = data.get("size")
    batch_size = data.get("batch_size")
    model_id = data.get("model_id")
    if not isinstance(aspect, str) or not isinstance(size, str):
        raise LensException("sidecar missing aspect_ratio or size")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise LensException("sidecar missing or invalid batch_size")
    if not isinstance(model_id, str):
        raise LensException("sidecar missing model_id")

    neg = data.get("negative_prompt")
    if neg is not None and not isinstance(neg, str):
        raise LensException("sidecar negative_prompt must be a string")

    slug = _validate_slug(_slug_from_sidecar_path(path))

    ref_paths: tuple[str, ...] = ()
    raw_refs = data.get("refs")
    if raw_refs is not None:
        if not isinstance(raw_refs, list):
            raise LensException("sidecar refs must be a list of strings")
        ref_list = cast(list[Any], raw_refs)
        cleaned: list[str] = []
        for item in ref_list:
            if not isinstance(item, str):
                raise LensException("sidecar refs must be a list of strings")
            t = item.strip()
            if t:
                cleaned.append(t)
        ref_paths = tuple(cleaned)

    return BatchSidecarParams(
        prompt=prompt_text,
        negative_prompt=neg,
        aspect_ratio=aspect,
        size=size,
        batch_size=batch_size,
        model_id=model_id,
        slug=slug,
        ref_paths=ref_paths,
    )


def prepare_batch(
    session: ProjectSession,
    prompt: str | None,
    *,
    aspect: str | None = None,
    size: str | None = None,
    batch: int | None = None,
    slug: str | None = None,
    negative_prompt: str | None = None,
    model_id: str | None = None,
    from_sidecar: Path | str | None = None,
    ref_paths: Sequence[str] | None = None,
) -> tuple[BatchPlan, ImageBackend]:
    sc: BatchSidecarParams | None = None
    if from_sidecar is not None:
        sc_path = resolve_sidecar_path(session.project_root, from_sidecar)
        sc = read_batch_sidecar(sc_path)

    if prompt is not None and str(prompt).strip() != "":
        eff_prompt = str(prompt)
    else:
        eff_prompt = (sc.prompt if sc else None) or ""

    if not eff_prompt or not str(eff_prompt).strip():
        raise LensException(
            "prompt is required (or use --from with a valid sidecar)"
        )

    eff_model = model_id if model_id is not None else (sc.model_id if sc else None)
    descriptor, image_backend = image_registry.resolve(session.project_root, eff_model)

    eff_aspect = (
        aspect if aspect is not None else (sc.aspect_ratio if sc else None)
    )
    eff_size = size if size is not None else (sc.size if sc else None)
    eff_batch = batch if batch is not None else (sc.batch_size if sc else None)
    eff_slug = slug if slug is not None else (sc.slug if sc else None)
    eff_negative = (
        negative_prompt
        if negative_prompt is not None
        else (sc.negative_prompt if sc else None)
    )

    if eff_aspect is None:
        eff_aspect = descriptor.aspect_ratios[0]
    if eff_size is None:
        eff_size = descriptor.sizes[0]
    if eff_batch is None:
        eff_batch = 1

    eff_aspect = _validate_aspect(descriptor, eff_aspect)
    eff_size = _validate_size(descriptor, eff_size)
    eff_batch = _validate_batch(descriptor, eff_batch)

    _enforce_prompt_length(
        eff_prompt, limit=descriptor.max_prompt_chars, label="raw prompt"
    )
    prompt_resolved = _resolve_prompt(eff_prompt, session)
    _enforce_prompt_length(
        prompt_resolved,
        limit=descriptor.max_prompt_chars,
        label="resolved prompt (after @-expansion)",
    )

    final_slug = _validate_slug(
        (eff_slug or "").strip() or prompt_to_slug(prompt_resolved)
    )
    session_dir = f"generated/{final_slug}"

    normalized_refs: list[str]
    if ref_paths is not None:
        normalized_refs = []
        for r in ref_paths:
            t = str(r).strip()
            if t:
                normalized_refs.append(t)
    else:
        normalized_refs = list(sc.ref_paths) if sc else []
    input_urls: tuple[str, ...] = ()
    if normalized_refs:
        if not descriptor.supports_reference_images:
            raise LensException(
                "reference images (--ref / refs) are not supported for this image API"
            )
        input_urls = presign_mount_read_urls(
            session.project_root,
            normalized_refs,
            expires_in=DEFAULT_MEDIA_PRESIGN_TTL_SECONDS,
        )

    spec = ImageSpec(
        prompt=prompt_resolved,
        negative_prompt=eff_negative,
        aspect_ratio=eff_aspect,
        size=eff_size,
        batch=eff_batch,
        model_id=descriptor.id,
        input_image_urls=input_urls,
    )
    plan = BatchPlan(
        descriptor=descriptor,
        spec=spec,
        slug=final_slug,
        session_dir=session_dir,
        prompt_raw=eff_prompt,
        prompt_resolved=prompt_resolved,
        reference_paths=tuple(normalized_refs),
    )
    return (plan, image_backend)


def plan_from_persisted_params(
    session: ProjectSession,
    *,
    slug: str,
    prompt_raw: str,
    prompt_resolved: str,
    model_id: str,
    aspect_ratio: str,
    size: str,
    batch_size: int,
    negative_prompt: str | None = None,
    reference_paths: Sequence[str] | None = None,
) -> BatchPlan:
    """Build a :class:`BatchPlan` for incremental saves using stored prompts (no ``@`` re-resolution)."""
    descriptor, _ = image_registry.resolve(session.project_root, model_id)
    ar = _validate_aspect(descriptor, aspect_ratio)
    sz = _validate_size(descriptor, size)
    bt = _validate_batch(descriptor, batch_size)
    final_slug = _validate_slug(slug)
    session_dir = f"generated/{final_slug}"
    refs_tuple: tuple[str, ...]
    if reference_paths is not None:
        refs_tuple = tuple(
            t for t in (str(r).strip() for r in reference_paths) if t
        )
    else:
        refs_tuple = ()
    input_urls: tuple[str, ...] = ()
    if refs_tuple:
        if not descriptor.supports_reference_images:
            raise LensException(
                "reference images (--ref / refs) are not supported for this image API"
            )
        input_urls = presign_mount_read_urls(
            session.project_root,
            refs_tuple,
            expires_in=DEFAULT_MEDIA_PRESIGN_TTL_SECONDS,
        )
    spec = ImageSpec(
        prompt=prompt_resolved,
        negative_prompt=negative_prompt,
        aspect_ratio=ar,
        size=sz,
        batch=bt,
        model_id=descriptor.id,
        input_image_urls=input_urls,
    )
    return BatchPlan(
        descriptor=descriptor,
        spec=spec,
        slug=final_slug,
        session_dir=session_dir,
        prompt_raw=prompt_raw,
        prompt_resolved=prompt_resolved,
        reference_paths=refs_tuple,
    )


def save_generated_item(
    session: ProjectSession,
    plan: BatchPlan,
    *,
    item_data: bytes,
    ext: str,
    batch_seq: int | None = None,
) -> SavedItem:
    """Persist one image under ``plan.session_dir``; first save allocates batch and sidecar."""
    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException("no mount_point configured in lens.toml")
    session_dir = plan.session_dir
    spec = plan.spec
    descriptor = plan.descriptor
    ext_clean = ext.lstrip(".")
    if batch_seq is None:
        next_batch = _next_batch_seq(backend, session_dir)
        result_seq = 1
        sidecar = _build_sidecar(
            spec=spec,
            descriptor=descriptor,
            prompt_raw=plan.prompt_raw,
            prompt_resolved=plan.prompt_resolved,
            batch_seq=next_batch,
            reference_paths=plan.reference_paths,
        )
        sidecar_name = f"b_{next_batch}.yaml"
        sidecar_bytes = yaml.safe_dump(
            sidecar, sort_keys=False, allow_unicode=True
        ).encode("utf-8")
        backend.put_file(
            session_dir, sidecar_name, io.BytesIO(sidecar_bytes)
        )
        sidecar_path = f"{session_dir}/{sidecar_name}"
        bseq = next_batch
        sidecar_created = True
    else:
        bseq = batch_seq
        result_seq = _next_result_seq_in_batch(
            backend, session_dir, bseq
        )
        names = [
            str(e.get("name", ""))
            for e in (backend.list_dir(session_dir) or [])
            if not e.get("is_dir")
        ]
        yml = f"b_{bseq}.yaml"
        yml2 = f"b_{bseq}.yml"
        if not any(n.lower() in (yml.lower(), yml2.lower()) for n in names):
            raise LensException(
                f"no sidecar for batch {bseq} in {session_dir}; save first"
            )
        if yml2.lower() in {n.lower() for n in names} and yml.lower() not in {
            n.lower() for n in names
        }:
            sidecar_path = f"{session_dir}/{yml2}"
        else:
            sidecar_path = f"{session_dir}/{yml}"
        sidecar_created = False
    filename = f"b_{bseq}_r_{result_seq}.{ext_clean}"
    backend.put_file(
        session_dir, filename, io.BytesIO(item_data)
    )
    return SavedItem(
        batch_seq=bseq,
        result_seq=result_seq,
        path=f"{session_dir}/{filename}",
        sidecar_path=sidecar_path,
        sidecar_created=sidecar_created,
    )


async def _consume_backend(
    backend: Any, spec: ImageSpec
) -> tuple[list[ItemReady], str | None]:
    items: list[ItemReady] = []
    err: str | None = None
    async for event in backend.generate(spec):
        if isinstance(event, Progress):
            continue
        if isinstance(event, ItemReady):
            items.append(event)
        elif isinstance(event, Error):
            err = event.message
            break
        elif isinstance(event, Done):
            break
    return items, err


def generate(
    session: ProjectSession,
    prompt: str | None,
    *,
    aspect: str | None = None,
    size: str | None = None,
    batch: int | None = None,
    slug: str | None = None,
    negative_prompt: str | None = None,
    model_id: str | None = None,
    from_sidecar: Path | str | None = None,
    ref_paths: Sequence[str] | None = None,
) -> GenerateResult:
    """Run a media-generation request end-to-end: generate all items and save the batch.

    Merges ``--from`` sidecar fields the same way as the CLI. Raises
    :class:`LensException` for user-facing errors.
    """
    plan, image_backend = prepare_batch(
        session,
        prompt,
        aspect=aspect,
        size=size,
        batch=batch,
        slug=slug,
        negative_prompt=negative_prompt,
        model_id=model_id,
        from_sidecar=from_sidecar,
        ref_paths=ref_paths,
    )
    items, err = asyncio.run(
        _consume_backend(image_backend, plan.spec)
    )
    if err is not None:
        raise LensException(f"image generation failed: {err}")
    if not items:
        raise LensException("image generation returned no images")

    saved_paths: list[str] = []
    batch_var: int | None = None
    first_sidecar_path = ""
    for item in items:
        saved = save_generated_item(
            session,
            plan,
            item_data=item.data,
            ext=item.ext,
            batch_seq=batch_var,
        )
        batch_var = saved.batch_seq
        saved_paths.append(saved.path)
        if saved.sidecar_created:
            first_sidecar_path = saved.sidecar_path
    if batch_var is None:
        raise RuntimeError("save_generated_item must run at least once")
    return GenerateResult(
        slug=plan.slug,
        batch_seq=batch_var,
        paths=saved_paths,
        sidecar_path=first_sidecar_path,
        prompt_resolved=plan.prompt_resolved,
        descriptor_id=plan.descriptor.id,
    )
