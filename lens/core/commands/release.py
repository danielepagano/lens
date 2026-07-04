"""Core helpers for the release decision engine (`lens release`)."""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import tomli_w

from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.release.config import (
    DatasetRepoConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_release_config,
    validate_deploy_topology,
)
from lens.core.release.status import ReleaseStatus, compute_release_status
from lens.core.release.version import (
    SemverTag,
    latest_overall,
    latest_within_major,
    parse_semver_tag,
)


@dataclass(frozen=True)
class ReleaseCheckResult:
    action: str  # "none" | "apply" | "await_approval"
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


def execute_release_check(project_root: Path) -> ReleaseCheckResult:
    status = compute_release_status(project_root)
    if not status.enabled:
        return ReleaseCheckResult(action="none", summary="release system not enabled")

    if status.gated_update_pending and status.gated_update_approved:
        target = status.gated_update_target_version
        if not target:
            raise LensException("gated_update_target_version is required when approval is true")
        summary = f"gated update {target} approved; ready to apply"
        return ReleaseCheckResult(action="apply", target=target, summary=summary)

    target_tag = _select_target_tag(status)
    if target_tag is None:
        if status.gated_update_pending and not status.gated_update_approved:
            target = status.gated_update_target_version
            summary = f"awaiting approval for gated update {target}"
            return ReleaseCheckResult(action="await_approval", target=target, summary=summary)
        return ReleaseCheckResult(action="none", summary="no release action required")

    installed_semver = status.installed_semver
    if installed_semver is None:
        installed_semver = _semver_from_version_string(status.local_checkout_version)

    target_semver = _semver_from_version_string(target_tag)
    if target_semver is None:
        raise LensException("target release tag is not a valid vMAJOR.MINOR.PATCH value")

    if installed_semver is not None and target_semver == installed_semver:
        # Clear requested_version if it was the source of the target and is
        # already fulfilled — otherwise it lingers and blocks auto_update.
        if status.requested_version.strip():
            req_semver = _semver_from_version_string(status.requested_version)
            if req_semver is not None and req_semver.tag == target_tag:
                _update_release_section(
                    project_root,
                    {"requested_version": ""},
                    commit_message="release: clear fulfilled requested_version",
                )
        return ReleaseCheckResult(action="none", summary="already at target version")

    if installed_semver is not None and target_semver < installed_semver:
        raise LensException(
            "requested version is older than the currently installed version"
        )

    if installed_semver is not None and target_semver.major > installed_semver.major:
        _mark_gated_pending(project_root, target_tag)
        summary = f"gated update {target_tag} pending approval"
        return ReleaseCheckResult(action="await_approval", target=target_tag, summary=summary)

    summary = f"apply release {target_tag}"
    return ReleaseCheckResult(action="apply", target=target_tag, summary=summary)


def execute_release_apply(project_root: Path, target_tag: str) -> ReleaseApplyResult:
    raw_config = _read_lens_toml(project_root)
    cfg = parse_release_config(raw_config)
    if not cfg.enabled:
        raise LensException("release system is not enabled")
    url = cfg.lens_repo_url.strip()
    if not url:
        raise LensException("[release].lens_repo_url must be set")
    normalized_tag = target_tag.strip()
    target_semver = _semver_from_version_string(normalized_tag)
    if target_semver is None:
        raise LensException("--to must be a valid vMAJOR.MINOR.PATCH tag")

    summary = f"release apply target {normalized_tag}"

    updates: dict[str, bool | str] = {}

    # Clear gated-update fields if this was an approved major bump
    if cfg.gated_update_approved and cfg.gated_update_target_version == normalized_tag:
        updates["gated_update_pending"] = False
        updates["gated_update_target_version"] = ""
        updates["gated_update_approved"] = False

    # Clear requested_version when the applied tag fulfills it
    if cfg.requested_version.strip():
        req_semver = _semver_from_version_string(cfg.requested_version)
        if req_semver is not None and req_semver.tag == normalized_tag:
            updates["requested_version"] = ""

    if updates:
        _update_release_section(
            project_root,
            updates,
            commit_message=f"release apply {normalized_tag}",
        )
        summary = f"cleared state for {normalized_tag}"

    return ReleaseApplyResult(lens_repo_url=url, tag=normalized_tag, summary=summary)


def execute_release_policy_update(
    session: ProjectSession,
    *,
    auto_update: str | None = None,
    requested_version: str | None = None,
) -> None:
    """Update ``[release]`` policy fields and commit+push via *session*'s Storage.

    Only the fields explicitly passed (not ``None``) are updated in
    ``lens.toml``.  The commit message is ``"release: update policy"``.
    Push is attempted only when a remote is configured.
    """
    storage = session.new_storage(owner=None)
    project_root = session.project_root

    if auto_update is not None and auto_update not in ("off", "minor", "major"):
        raise LensException(
            "auto_update must be 'off', 'minor', or 'major', "
            f"got {auto_update!r}"
        )

    updates: dict[str, bool | str] = {}
    if auto_update is not None:
        updates["auto_update"] = auto_update
    if requested_version is not None:
        updates["requested_version"] = requested_version
    if not updates:
        return

    lens_toml = project_root / "lens.toml"
    raw = lens_toml.read_text(encoding="utf-8")
    updated = _apply_release_updates(raw, updates)
    if updated == raw:
        return

    storage.write_file(lens_toml, updated)
    storage.commit("release: update policy")
    if storage.has_remote():
        storage.push_or_raise()


def execute_release_gated_approve(session: ProjectSession) -> None:
    """Set ``gated_update_approved = true`` and commit+push.

    Does nothing if the change would be a no-op (already approved).
    """
    storage = session.new_storage(owner=None)
    lens_toml = session.project_root / "lens.toml"
    raw = lens_toml.read_text(encoding="utf-8")
    updated = _apply_release_updates(raw, {"gated_update_approved": True})
    if updated == raw:
        return
    storage.write_file(lens_toml, updated)
    storage.commit("release: approve gated update")
    if storage.has_remote():
        storage.push_or_raise()


def execute_release_gated_reject(session: ProjectSession) -> None:
    """Clear pending gated-update fields and commit+push (reject a major bump).

    Clears ``gated_update_pending``, ``gated_update_target_version``, and
    ``gated_update_approved``.  Does nothing if there is no pending gated
    update (checked against the *parsed* config, not raw text, so this is a
    true no-op rather than writing out already-default values as explicit
    lines).  Rejection is a "not now", not a "never" — the next ``check``
    run will re-evaluate the target from scratch.
    """
    lens_toml = session.project_root / "lens.toml"
    raw = lens_toml.read_text(encoding="utf-8")
    cfg = parse_release_config(tomllib.loads(raw))
    if not cfg.gated_update_pending:
        return

    storage = session.new_storage(owner=None)
    updated = _apply_release_updates(
        raw,
        {
            "gated_update_pending": False,
            "gated_update_target_version": "",
            "gated_update_approved": False,
        },
    )
    if updated == raw:
        return
    storage.write_file(lens_toml, updated)
    storage.commit("release: reject gated update")
    if storage.has_remote():
        storage.push_or_raise()


def _select_target_tag(status: ReleaseStatus) -> str | None:
    requested = status.requested_version.strip()
    if requested:
        semver = _semver_from_version_string(requested)
        if semver is None:
            raise LensException("requested_version must be a valid vMAJOR.MINOR.PATCH tag")
        return semver.tag

    if status.auto_update == "off":
        return None

    installed_semver = status.installed_semver
    if installed_semver is None:
        installed_semver = _semver_from_version_string(status.local_checkout_version)

    if status.auto_update == "major":
        candidate = latest_overall(status.available_tags)
    else:  # minor
        if installed_semver is None:
            return None
        candidate = latest_within_major(status.available_tags, installed_semver.major)

    if candidate is None:
        return None
    return candidate.tag


def _semver_from_version_string(value: str | None) -> SemverTag | None:
    if not value:
        return None
    trimmed = value.strip()
    core = trimmed.split("+", 1)[0]
    core = core.split("-", 1)[0]
    return parse_semver_tag(core)


def _mark_gated_pending(project_root: Path, target: str) -> None:
    _update_release_section(
        project_root,
        {
            "gated_update_pending": True,
            "gated_update_target_version": target,
            "gated_update_approved": False,
        },
        commit_message=f"release gated update pending {target}",
    )


def _update_release_section(
    project_root: Path,
    updates: Mapping[str, bool | str],
    *,
    commit_message: str,
) -> None:
    path = project_root / "lens.toml"
    raw = path.read_text(encoding="utf-8")
    updated = _apply_release_updates(raw, updates)
    if updated == raw:
        return
    path.write_text(updated, encoding="utf-8")
    try:
        _git_commit_and_push(project_root, commit_message)
    except LensException:
        path.write_text(raw, encoding="utf-8")
        raise


def _tomli_value(val: bool | str) -> str:
    """Format a single TOML value using tomli_w for proper encoding."""
    raw = tomli_w.dumps({"x": val})
    return raw.rstrip("\n").split(" = ", 1)[1]


def _apply_release_updates(raw: str, updates: Mapping[str, bool | str]) -> str:
    lines: list[str] = raw.splitlines()
    ends_newline = raw.endswith("\n")
    release_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == "[release]":
            release_idx = idx
            break

    if release_idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[release]")
        for key, value in updates.items():
            lines.append(f"{key} = {_tomli_value(value)}")
        result = "\n".join(lines)
        if ends_newline:
            result += "\n"
        return result

    block_end = release_idx + 1
    while block_end < len(lines):
        stripped = lines[block_end].strip()
        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[release]":
            break
        block_end += 1

    block_lines: list[str] = lines[release_idx + 1 : block_end]
    updated: list[str] = []
    handled: set[str] = set()
    for line in block_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            updated.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            updated.append(f"{key} = {_tomli_value(updates[key])}")
            handled.add(key)
        else:
            updated.append(line)

    for key, value in updates.items():
        if key not in handled:
            updated.append(f"{key} = {_tomli_value(value)}")

    lines[release_idx + 1 : block_end] = updated
    result = "\n".join(lines)
    if ends_newline:
        result += "\n"
    return result


def _git_commit_and_push(project_root: Path, message: str) -> None:
    _run_git(project_root, ["add", "lens.toml"])
    _run_git(project_root, ["commit", "-m", message])
    _run_git(project_root, ["push"])


def _run_git(project_root: Path, args: Iterable[str]) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "unknown error"
        raise LensException(f"git {' '.join(args)} failed: {detail}")


def _read_lens_toml(project_root: Path) -> dict[str, Any]:
    path = project_root / "lens.toml"
    with path.open("rb") as f:
        return tomllib.load(f)
