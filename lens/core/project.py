"""Project root discovery, slug validation, and active narrative."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import tomli_w

from lens.core.address import NarrativeAddress
from lens.core.narrative import NarrativeNode

if TYPE_CHECKING:
    from lens.core.knowledge import KnowledgeStore
    from lens.core.mount import MountBackend
    from lens.core.storage import Storage

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Dataset names that have a dedicated package under lens (sibling to core/cli).
# Used by CLI and tools discovery to load dataset-specific commands/operators.
DATASET_PACKAGES: dict[str, str] = {"dnd": "lens.dnd", "rpg": "lens.rpg"}


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


def get_selected_prompt_pack(project_root: Path) -> str | None:
    """Return prompt pack name from ``[project] prompt_pack``, or ``None``."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project", {})
    project: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}
    raw_pack = project.get("prompt_pack")
    if not isinstance(raw_pack, str):
        return None
    prompt_pack = raw_pack.strip()
    return prompt_pack if prompt_pack else None


def set_selected_prompt_pack(project_root: Path, prompt_pack: str | None) -> None:
    """Set or clear ``[project] prompt_pack`` in lens.toml."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise RuntimeError("no lens.toml found in this directory or any parent")
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        raw_project = {}
    project = cast(dict[str, Any], raw_project)
    if prompt_pack is None:
        project.pop("prompt_pack", None)
    else:
        project["prompt_pack"] = prompt_pack
    config["project"] = project
    lens_toml.write_bytes(tomli_w.dumps(config).encode("utf-8"))


def list_available_llms(project_root: Path) -> list[str]:
    """Return selectable LLM IDs from lens.toml.

    The first ``[[llm]]`` entry returns its id if present, otherwise ``[default]``.
    Subsequent entries are only included if they have an explicit id.
    Returns empty list if lens.toml doesn't exist or has no ``[[llm]]`` entries.
    """
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return []
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_llm_list = config.get("llm", [])
    llm_list: list[Any] = cast(list[Any], raw_llm_list) if isinstance(raw_llm_list, list) else []

    result: list[str] = []
    for i, raw_entry in enumerate(llm_list):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        entry_id = entry.get("id")
        if i == 0:
            result.append(entry_id if isinstance(entry_id, str) else "[default]")
        elif isinstance(entry_id, str):
            result.append(entry_id)
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


def has_mount_config(project_root: Path) -> bool:
    """Return ``True`` if ``mount_point`` is set in ``lens.toml`` (any backend)."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return False
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        return False
    project = cast(dict[str, Any], raw_project)
    raw = project.get("mount_point")
    return isinstance(raw, str) and bool(raw.strip())


def get_mount_point(project_root: Path) -> Path | None:
    """Return the resolved mount_point path from [project] in lens.toml, or None.

    Returns ``None`` for S3 URIs (``s3://...``) — use :func:`get_mount_backend` instead.
    """
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        return None
    project = cast(dict[str, Any], raw_project)
    raw = project.get("mount_point")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if raw.startswith("s3://"):
        return None
    p = Path(raw)
    return p if p.is_absolute() else (project_root / p).resolve()


def get_mount_backend(project_root: Path) -> "MountBackend | None":
    """Return a :class:`~lens.core.mount.MountBackend` for the configured mount_point, or ``None``.

    Reads ``mount_point`` from ``[project]`` in ``lens.toml``:

    - A local path (relative or absolute) → :class:`~lens.core.mount.LocalMountBackend`.
    - An ``s3://`` URI → :class:`~lens.core.mount.S3MountBackend` using standard
      AWS environment variables for credentials and endpoint.
    """
    from lens.core.mount import LocalMountBackend, get_backend_from_uri

    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        return None
    project = cast(dict[str, Any], raw_project)
    raw = project.get("mount_point")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if raw.startswith("s3://"):
        return get_backend_from_uri(raw)
    p = Path(raw)
    root = p if p.is_absolute() else (project_root / p).resolve()
    return LocalMountBackend(root)


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
