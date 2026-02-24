"""Project root discovery, slug validation, and active narrative."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.narrative import NarrativeNode

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def find_git_root() -> Path | None:
    path = Path.cwd().resolve()
    while path != path.parent:
        if (path / ".git").exists():
            return path
        path = path.parent
    return None


def find_project_root() -> Path | None:
    path = Path.cwd().resolve()
    while path != path.parent:
        if (path / "lens.toml").exists():
            return path
        path = path.parent
    return None


def validate_slug(slug: str) -> bool:
    return bool(_SLUG_PATTERN.fullmatch(slug))


def get_active_narrative(project_root: Path) -> NarrativeNode | None:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        return None
    project = cast(dict[str, Any], raw_project)
    narrative = project.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    narrative_dir = project_root / "narrative" / narrative
    if not narrative_dir.exists() or not narrative_dir.is_dir():
        return None
    return NarrativeNode(narrative_root=narrative_dir, key_path=())
