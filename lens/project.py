"""Project root discovery, slug validation, and active narrative."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.narrative import NarrativeNode

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def find_git_root_from(start: Path) -> Path:
    """Walk up from *start* and return the nearest directory containing ``.git``.

    Raises ``RuntimeError`` if no git repository is found.
    """
    path = start.resolve()
    while path != path.parent:
        if (path / ".git").exists():
            return path
        path = path.parent
    raise RuntimeError(
        f"'{start}' is not inside a git repository (run 'git init' first)"
    )


def find_git_root() -> Path:
    """Return the git root for the current working directory.

    Raises ``RuntimeError`` if not inside a git repository.
    """
    return find_git_root_from(Path.cwd())


def find_project_root() -> Path:
    """Walk up from CWD and return the nearest directory containing ``lens.toml``.

    Raises ``RuntimeError`` if no Lens project is found.
    """
    path = Path.cwd().resolve()
    while path != path.parent:
        if (path / "lens.toml").exists():
            return path
        path = path.parent
    raise RuntimeError(
        "no lens.toml found in this directory or any parent (run 'lens init' first)"
    )


def validate_slug(slug: str) -> bool:
    return bool(_SLUG_PATTERN.fullmatch(slug))


def require_lens_context(start: Path) -> tuple[Path, Path]:
    """Return ``(git_root, project_root)`` for the Lens project containing *start*.

    Performs the same two checks as the CLI preflight — git repository present
    and ``lens.toml`` reachable — and raises ``RuntimeError`` with an actionable
    message if either is missing.  Callers never need to handle ``None``.
    """
    git_root = find_git_root_from(start)
    p = start.resolve()
    while p != p.parent:
        if (p / "lens.toml").exists():
            return git_root, p
        p = p.parent
    raise RuntimeError(
        f"'{start}' is not inside an initialized Lens project "
        "(run 'lens init' first)"
    )


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
