"""Core helpers for the release decision engine (`lens release`).

Per decision #4 in docs/release-system.md: CI's job is a single, stateless,
read-only parent-hash check. Nothing in this module writes to git.
"""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lens.core.exceptions import LensException
from lens.core.release.config import (
    DatasetRepoConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_release_config,
    validate_deploy_topology,
)
from lens.core.release.version import parse_semver_tag


@dataclass(frozen=True)
class ReleaseCheckResult:
    action: str  # "none" | "apply"
    target: str | None = None
    summary: str = ""


@dataclass(frozen=True)
class ReleaseApplyResult:
    lens_repo_url: str
    tag: str
    summary: str


def resolve_release_project_root(cwd: Path) -> Path:
    """Resolve the project root ``lens release check``/``apply`` should act on.

    Supports two call sites:

    - **Inside a project** (``lens.toml`` present at *cwd* or an ancestor):
      that project is the target, exactly like any other ``lens`` command.
      This covers single-project Fly apps (``fly.toml`` lives alongside
      ``lens.toml``) as well as running from inside one sibling project of a
      multi-project app.
    - **At a multi-project deploy directory** — either a bare
      parent-of-projects directory holding ``fly.toml`` directly (no
      sibling ``lens.toml``), or its grandparent when ``fly.toml`` is
      colocated inside the release leader's own project directory (see
      "Multi-project deployments" in ``deploy/README.md``): resolves to
      whichever served project is the release leader
      (``[release] app_leader = true``), after validating the deploy
      topology (:func:`validate_deploy_topology`: exactly one leader, no
      conflicting ``[[dataset_repo]]`` declarations across siblings).

    Raises ``RuntimeError`` (no ``lens.toml`` and no ``fly.toml`` anywhere up
    the tree — same error `lens` commands normally raise) or
    ``LensException`` (multi-project topology present but invalid, or no
    leader designated).
    """
    from lens.core.commands.deploy import (
        build_projects,
        find_colocated_fly_toml,
        get_slugs,
        read_lens_toml,
    )
    from lens.core.project import find_project_root, find_project_root_if_any

    project_root = find_project_root_if_any(cwd)
    if project_root is not None:
        return project_root

    direct_fly_toml = cwd / "fly.toml"
    fly_toml = direct_fly_toml if direct_fly_toml.exists() else find_colocated_fly_toml(cwd)
    if fly_toml is None:
        # Neither a project nor a deploy directory — raise the standard,
        # already-clear "no lens.toml found" error rather than a
        # git-specific one.
        return find_project_root()

    slugs = get_slugs(fly_toml)
    if not slugs:
        raise LensException(f"{fly_toml} has no project slugs (LENS_PROJECT_SLUGS is empty)")

    projects = build_projects(fly_toml.parent, slugs)
    project_configs: list[tuple[str, ReleaseConfig, list[DatasetRepoConfig]]] = []
    leader_root: Path | None = None
    for slug, _git_root, proj_root in projects:
        raw = read_lens_toml(proj_root)
        cfg = parse_release_config(raw)
        dataset_repos = parse_dataset_repo_configs(raw)
        project_configs.append((slug, cfg, dataset_repos))
        if cfg.app_leader:
            leader_root = proj_root

    validate_deploy_topology(project_configs)

    if leader_root is None:
        raise LensException(
            f"{fly_toml} serves {len(slugs)} projects but none set "
            "[release] app_leader = true; designate exactly one release "
            "leader to run 'lens release' from this directory"
        )
    return leader_root


def _git_rev_list_parents(project_root: Path, since: str | None) -> list[str]:
    """Return the parent commit SHAs for the range ``since..HEAD``.

    When *since* is ``None``, returns just HEAD's first parent.  Each
    returned SHA is the "parent" side of a parent-child edge introduced
    by the commits in the range.
    """
    if since is None:
        cmd = ["git", "rev-parse", "HEAD"]
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
        if result.returncode != 0:
            raise LensException(f"git rev-parse HEAD failed: {result.stderr.strip()}")
        head = result.stdout.strip()
        cmd = ["git", "rev-parse", f"{head}^1"]
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        return [result.stdout.strip()]

    cmd = ["git", "rev-list", "--parents", f"{since}..HEAD"]
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if result.returncode != 0:
        raise LensException(
            f"git rev-list --parents {since}..HEAD failed: {result.stderr.strip()}"
        )

    parents: list[str] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            parents.extend(parts[1:])
    return parents


def execute_release_check(
    project_root: Path,
    since: str | None = None,
) -> ReleaseCheckResult:
    """Check whether the push producing this commit should trigger a release.

    Reads ``requested_version`` and ``requested_from_commit`` from the
    project's ``lens.toml``.  When *since* is provided (the commit before
    the push range, e.g. ``${{ github.event.before }}``), checks every
    commit in ``since..HEAD`` — if any of those commits has
    ``requested_from_commit`` as its parent, the request is fulfilled and
    the result says ``"apply"``.  Without *since* (standalone/local check),
    only HEAD's first parent is compared.

    Returns ``{"action": "apply", "target": "<tag>"}`` or
    ``{"action": "none"}``.  No git writes occur in any case.
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        return ReleaseCheckResult(action="none", summary="release system not enabled")

    requested = cfg.requested_version.strip()
    if not requested:
        return ReleaseCheckResult(action="none", summary="no version requested")

    sanity = parse_semver_tag(requested)
    if sanity is None:
        raise LensException(
            f"requested_version {requested!r} is not a valid vMAJOR.MINOR.PATCH tag"
        )

    from_commit = cfg.requested_from_commit.strip()
    if not from_commit:
        return ReleaseCheckResult(action="none", summary="requested_from_commit is empty")

    parents = _git_rev_list_parents(project_root, since)
    if from_commit in parents:
        return ReleaseCheckResult(
            action="apply",
            target=sanity.tag,
            summary=f"parent match on {from_commit}; deploy {sanity.tag}",
        )

    return ReleaseCheckResult(
        action="none",
        summary=f"no commit in range has {from_commit} as parent",
    )


def execute_release_apply(project_root: Path, target_tag: str) -> ReleaseApplyResult:
    """Print build parameters for the requested tag.

    **No git writes occur** — this only validates config, parses the tag,
    and returns the Lens repo URL + tag CI needs.  Decision #4: CI never
    writes back to git.
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        raise LensException("release system is not enabled")
    url = cfg.lens_repo_url.strip()
    if not url:
        raise LensException("[release].lens_repo_url must be set")
    normalized_tag = target_tag.strip()
    target_semver = parse_semver_tag(normalized_tag)
    if target_semver is None:
        raise LensException("--to must be a valid vMAJOR.MINOR.PATCH tag")

    return ReleaseApplyResult(
        lens_repo_url=url,
        tag=normalized_tag,
        summary=f"release apply target {normalized_tag}",
    )


def _read_lens_toml(project_root: Path) -> dict[str, Any]:
    path = project_root / "lens.toml"
    with path.open("rb") as f:
        return tomllib.load(f)
