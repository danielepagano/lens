"""Project root discovery and slug validation."""

from __future__ import annotations

import re
from pathlib import Path

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
