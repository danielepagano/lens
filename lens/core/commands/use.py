from __future__ import annotations

import io
import re
import tomllib
from pathlib import Path
from typing import Any, Literal, cast
import tomli_w

from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore, parse_id
from lens.core.narrative import NarrativeNode
from lens.core.pinning import pin, set_param
from lens.core.project import (
    find_git_root_from,
    find_project_root,
    get_selected_datasets,
    validate_slug,
)
from lens.core.storage import Storage

_COMPANION_BOOTSTRAP_HINT = (
    "Starter KB objects were created from templates where needed. "
    "Finish them in Knowledge or run the design operator for a guided setup "
    "(see the companion dataset README)."
)


def _proper_title_from_kb_key(key: str) -> str:
    segments = re.split(r"[-_]+", key)
    return " ".join(s[:1].upper() + s[1:].lower() if s else "" for s in segments)


def _ensure_companion_kb_objects(
    project_root: Path,
    storage: Storage,
    as_kb_id: str,
    with_kb_id: str,
) -> None:
    kb = KnowledgeStore.for_project(project_root, storage=storage)
    for kid in (as_kb_id, with_kb_id):
        if not kb.exists(kid):
            kb.store_object(kid, None, use_template=True)


def _bootstrap_companion_chat_root(
    *,
    project_root: Path,
    git_root: Path,
    slug: str,
    as_kb_id: str,
    with_kb_id: str,
) -> None:
    try:
        as_type, as_key = parse_id(as_kb_id)
        with_type, with_key = parse_id(with_kb_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    if as_type != "companion":
        raise LensException(
            f"companion chat expects a companion.* id for the companion role (got '{as_kb_id}')"
        )
    if with_type != "human":
        raise LensException(
            f"companion chat expects a human.* id for the human role (got '{with_kb_id}')"
        )

    datasets = get_selected_datasets(project_root)
    if "companion" not in datasets:
        raise LensException(
            "companion chat requires the companion dataset in [project] datasets"
        )

    storage = Storage(git_root)
    _ensure_companion_kb_objects(project_root, storage, as_kb_id, with_kb_id)

    narrative_dir = project_root / "narrative" / slug
    root_node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    node_path = narrative_dir / "_node.md"
    title_a = _proper_title_from_kb_key(as_key)
    title_b = _proper_title_from_kb_key(with_key)
    heading = f"# {title_a} & {title_b}\n"
    storage.write_file(node_path, heading)
    pin(root_node, [f"{as_kb_id}+", f"{with_kb_id}+"], storage)
    set_param(root_node, "chat", "as_kb_id", as_kb_id, storage)
    set_param(root_node, "chat", "with_kb_id", with_kb_id, storage)


def use_narrative_for_project(
    slug: str,
    project_root: Path,
    git_root: Path,
    *,
    narrative_kind: Literal["default", "companion_chat"] = "default",
    companion_as_kb_id: str | None = None,
    companion_with_kb_id: str | None = None,
) -> str | None:
    """Switch the active narrative in *project_root* to *slug*, creating it if necessary.

    Separated from ``use_narrative`` so the API server can call it without
    relying on the current working directory.

    Returns an optional user-facing hint when companion bootstrap ran.
    """
    storage = Storage(git_root)
    lens_toml = project_root / "lens.toml"
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_project = config.get("project", {})
    project: dict[str, Any] = (
        dict(cast(dict[str, Any], raw_project)) if isinstance(raw_project, dict) else {}
    )
    project["narrative"] = slug
    config["project"] = project

    buf = io.BytesIO()
    tomli_w.dump(config, buf)
    storage.write_file_bytes(lens_toml, buf.getvalue())

    narrative_dir = project_root / "narrative" / slug
    storage.mkdir(narrative_dir)

    node_path = narrative_dir / "_node.md"
    if narrative_kind == "companion_chat":
        if not companion_as_kb_id or not companion_with_kb_id:
            raise LensException(
                "companion chat requires both companion (companion.*) and human (human.*) KB ids"
            )
        _bootstrap_companion_chat_root(
            project_root=project_root,
            git_root=git_root,
            slug=slug,
            as_kb_id=companion_as_kb_id.strip(),
            with_kb_id=companion_with_kb_id.strip(),
        )
        return _COMPANION_BOOTSTRAP_HINT

    if not node_path.exists():
        storage.write_file(node_path, f"# {slug}\n")
    return None


def use_narrative(
    slug: str,
    *,
    narrative_kind: Literal["default", "companion_chat"] = "default",
    companion_as_kb_id: str | None = None,
    companion_with_kb_id: str | None = None,
) -> str | None:
    if not slug.strip():
        raise LensException("SLUG cannot be empty.")
    if not validate_slug(slug):
        raise LensException(f"invalid slug '{slug}' (alphanumeric, underscores, hyphens only)")

    try:
        root = find_project_root()
        git_root = find_git_root_from(root)
    except RuntimeError as e:
        raise LensException(str(e)) from e

    return use_narrative_for_project(
        slug,
        root,
        git_root,
        narrative_kind=narrative_kind,
        companion_as_kb_id=companion_as_kb_id,
        companion_with_kb_id=companion_with_kb_id,
    )
