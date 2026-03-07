"""Project root discovery, slug validation, and active narrative."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from lens.core.address import NarrativeAddress
from lens.core.narrative import NarrativeNode

if TYPE_CHECKING:
    from lens.core.knowledge import KnowledgeStore
    from lens.core.storage import Storage

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Dataset names that have a dedicated package under lens (sibling to core/cli).
# Used by CLI and tools discovery to load dataset-specific commands/operators.
DATASET_PACKAGES: dict[str, str] = {"dnd": "lens.dnd"}


def datasets_root() -> Path:
    """Return the ``datasets/`` directory bundled with the Lens package."""
    return Path(__file__).parent.parent.parent / "datasets"


def get_selected_datasets(project_root: Path) -> list[str]:
    """Return the dataset names from ``[project] datasets`` in lens.toml, or [] if unset."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return []
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project", {})
    project: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}
    raw_names = project.get("datasets", [])
    dataset_names: list[Any] = cast(list[Any], raw_names) if isinstance(raw_names, list) else []
    result: list[str] = []
    for name in dataset_names:
        if isinstance(name, str):
            result.append(name)
    return result


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


def find_project_root_if_any(start: Path | None = None) -> Path | None:
    """Walk up from *start* (or CWD) and return the nearest directory containing
    ``lens.toml``, or ``None`` if none is found.
    """
    path = (start or Path.cwd()).resolve()
    while path != path.parent:
        if (path / "lens.toml").exists():
            return path
        path = path.parent
    return None


def is_dataset_root(project_root: Path) -> bool:
    """Return True if lens.toml at *project_root* declares a dataset."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return False
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    return "dataset" in config


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


class ProjectSession:
    """Single source of truth for a Lens project's shared state.

    Holds (git_root, project_root) and provides:
    - .kb  — the singleton KnowledgeStore (tags cache persists for the lifetime
             of this process)
    - .new_storage(owner)  — factory for per-operation Storage instances
    """

    def __init__(self, git_root: Path, project_root: Path) -> None:
        self.git_root = git_root
        self.project_root = project_root
        self.active_narrative: NarrativeNode | None = get_active_narrative(project_root)

    @property
    def kb(self) -> KnowledgeStore:
        from lens.core.knowledge import KnowledgeStore
        return KnowledgeStore.for_project(self.project_root)

    def new_storage(self, owner: NarrativeAddress | None = None) -> Storage:
        """Create a fresh Storage for one operation."""
        from lens.core.storage import Storage
        return Storage(self.git_root, owner=owner)

    @classmethod
    def from_cwd(cls) -> ProjectSession:
        git_root, project_root = require_lens_context(Path.cwd())
        return cls(git_root, project_root)


def resolve_address(
    addr: NarrativeAddress,
    project_root: Path,
) -> NarrativeAddress:
    """Fill in active narrative and resolve /@cursor to actual position."""
    if addr.narrative is None:
        active = get_active_narrative(project_root)
        if active is None:
            raise ValueError("no active narrative set in lens.toml")
        addr = addr.with_narrative(active.narrative_root.name)
    if addr.cursor:
        assert addr.narrative is not None
        narrative_root = project_root / "narrative" / addr.narrative
        root_node = NarrativeNode(narrative_root=narrative_root, key_path=())
        return root_node.find_cursor_address()
    return addr
