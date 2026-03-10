from __future__ import annotations

import io
import tomllib
from pathlib import Path
from typing import Any, cast
import tomli_w

from lens.core.project import find_git_root_from, find_project_root, validate_slug
from lens.core.storage import Storage
from lens.core.exceptions import LensException


def use_narrative_for_project(slug: str, project_root: Path, git_root: Path) -> None:
    """Switch the active narrative in *project_root* to *slug*, creating it if necessary.

    Separated from ``use_narrative`` so the API server can call it without
    relying on the current working directory.
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
    if not node_path.exists():
        storage.write_file(node_path, f"# {slug}\n")


def use_narrative(slug: str) -> None:
    if not slug.strip():
        raise LensException("SLUG cannot be empty.")
    if not validate_slug(slug):
        raise LensException(f"invalid slug '{slug}' (alphanumeric, underscores, hyphens only)")

    try:
        root = find_project_root()
        git_root = find_git_root_from(root)
    except RuntimeError as e:
        raise LensException(str(e)) from e

    use_narrative_for_project(slug, root, git_root)
