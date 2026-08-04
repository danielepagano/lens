from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.project import (
    ProjectSession,
    is_cloud_deployed,
    resolve_dataset_path,
)
from lens.core.release.config import parse_dataset_repo_configs


@dataclass
class RefreshEntry:
    name: str
    status: str  # "ok" | "error"
    action: str  # "up_to_date" | "fast_forwarded" | "cloned" | "reset" | "error"
    detail: str


@dataclass
class RefreshResult:
    entries: list[RefreshEntry] = field(default_factory=lambda: cast(list[RefreshEntry], []))

    @property
    def any_changed(self) -> bool:
        return any(
            e.action in ("fast_forwarded", "cloned", "reset") for e in self.entries
        )

    def format_cli(self) -> str:
        lines: list[str] = []
        for e in self.entries:
            icon = {"ok": "✓", "error": "✗"}.get(e.status, "?")
            lines.append(f"{icon} {e.name}: {e.detail}")
        return "\n".join(lines)


def _git_log(
    git_dir: Path,
    range_spec: str,
    env: dict[str, str],
) -> list[str]:
    """Return one-line commit log entries for *range_spec* (e.g. ``<old>..HEAD``)."""
    r = subprocess.run(
        ["git", "-C", str(git_dir), "log", "--oneline", range_spec],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.strip().split("\n") if line.strip()]


def _refresh_git_clone(
    name: str,
    clone_dir: Path,
    git_url: str,
    ref: str,
    *,
    reset: bool,
) -> RefreshEntry:
    """Fetch and fast-forward (or clone) a single dataset repo at *clone_dir*."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    if not (clone_dir / ".git").is_dir():
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", ref, git_url, str(clone_dir)],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            err = (e.stderr or "").strip() or "clone failed"
            return RefreshEntry(
                name=name,
                status="error",
                action="error",
                detail=f"clone failed: {err}",
            )
        return RefreshEntry(
            name=name,
            status="ok",
            action="cloned",
            detail=f"cloned {name} from {git_url}",
        )

    try:
        subprocess.run(
            ["git", "-C", str(clone_dir), "fetch", "-q", "origin"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip() or "fetch failed"
        return RefreshEntry(
            name=name,
            status="error",
            action="error",
            detail=f"fetch failed: {err}",
        )

    if reset:
        try:
            subprocess.run(
                ["git", "-C", str(clone_dir), "reset", "--hard", f"origin/{ref}"],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "-C", str(clone_dir), "clean", "-fd"],
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            err = (e.stderr or "").strip() or "reset failed"
            return RefreshEntry(
                name=name,
                status="error",
                action="error",
                detail=f"reset failed: {err}",
            )
        return RefreshEntry(
            name=name, status="ok", action="reset", detail="reset to match remote"
        )

    r = subprocess.run(
        ["git", "-C", str(clone_dir), "rev-list", "--count", f"HEAD..origin/{ref}"],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode == 0 and r.stdout.strip() == "0":
        return RefreshEntry(
            name=name,
            status="ok",
            action="up_to_date",
            detail="already up to date",
        )

    old_head = subprocess.run(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True, env=env,
    ).stdout.strip() or ""

    try:
        subprocess.run(
            ["git", "-C", str(clone_dir), "merge", "--ff-only", f"origin/{ref}"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip() or "fast-forward failed"
        return RefreshEntry(
            name=name,
            status="error",
            action="error",
            detail=f"fast-forward failed: {err}",
        )

    commits = _git_log(clone_dir, f"{old_head}..HEAD", env)
    summary = f"updated {name}"
    if commits:
        summary += "\n" + "\n".join(f"  {c}" for c in commits)

    return RefreshEntry(
        name=name,
        status="ok",
        action="fast_forwarded",
        detail=summary,
    )


def _locate_dataset_repo(project_root: Path, name: str) -> Path | None:
    """Resolve the directory where a dataset repo lives or should be cloned.

    In cloud mode, returns ``$LENS_PROJECT_DIR/_datasets/<name>`` (the canonical
    location managed by ``deploy/start.sh``).  Locally, returns the path that
    :func:`resolve_dataset_path` finds — if it's a git checkout — or ``None``
    (bundled datasets that ship with Lens are never refreshed).
    """
    resolved = resolve_dataset_path(project_root, name)
    if resolved is not None:
        if (resolved / ".git").is_dir():
            return resolved
    if is_cloud_deployed():
        base = Path(os.environ.get("LENS_PROJECT_DIR", "/data/repos"))
        return base / "_datasets" / name
    return None


def execute_refresh(
    session: ProjectSession, *, reset: bool = False
) -> RefreshResult:
    result = RefreshResult()
    storage = session.new_storage()

    # 1. Refresh project repo
    try:
        if reset:
            storage.refresh_reset_hard_to_upstream()
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="ok",
                    action="reset",
                    detail="reset to match remote",
                )
            )
        elif storage.needs_fast_forward():
            git_root = session.git_root
            old_head = subprocess.run(
                ["git", "-C", str(git_root), "rev-parse", "HEAD"],
                capture_output=True, text=True,
            ).stdout.strip() or ""
            storage.refresh_fast_forward()
            commits = _git_log(
                git_root, f"{old_head}..HEAD", {**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            summary = "updated project from remote"
            if commits:
                summary += "\n" + "\n".join(f"  {c}" for c in commits)
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="ok",
                    action="fast_forwarded",
                    detail=summary,
                )
            )
        else:
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="ok",
                    action="up_to_date",
                    detail="already up to date",
                )
            )
    except LensException as e:
        msg = str(e)
        if "no git remote" in msg:
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="ok",
                    action="up_to_date",
                    detail="no remote configured",
                )
            )
        elif "no upstream branch" in msg:
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="ok",
                    action="up_to_date",
                    detail="no upstream branch",
                )
            )
        else:
            result.entries.append(
                RefreshEntry(
                    name="project",
                    status="error",
                    action="error",
                    detail=msg,
                )
            )

    # 2. Refresh dataset repos
    lens_toml = session.project_root / "lens.toml"
    if lens_toml.exists():
        with lens_toml.open("rb") as f:
            raw_config: dict[str, Any] = tomllib.load(f)
        for repo in parse_dataset_repo_configs(raw_config):
            clone_dir = _locate_dataset_repo(session.project_root, repo.name)
            if clone_dir is None:
                result.entries.append(
                    RefreshEntry(
                        name=repo.name,
                        status="ok",
                        action="up_to_date",
                        detail="bundled dataset — no refresh needed",
                    )
                )
                continue
            entry = _refresh_git_clone(
                repo.name, clone_dir, repo.git_url, repo.ref, reset=reset
            )
            result.entries.append(entry)

    session.kb.evict_tag_cache()
    KnowledgeStore.clear_registry()
    MediaService.clear_registry()
    return result
