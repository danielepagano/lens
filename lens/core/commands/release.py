"""Core helpers for the release system (`lens release`).

Two systems live here:

1. **CI-triggered release** — ``execute_release_check`` (parent-hash matching)
   and ``execute_release_apply`` emit a CI contract for ``release.sh``.
   No git writes occur; CI never writes back.

2. **Human / desktop interactions** — ``execute_release_request`` and
   ``execute_release_clear`` let a user (or the web UI) record or cancel a
   version deployment request by writing ``requested_version`` /
   ``requested_from_commit`` into ``lens.toml`` (one uncommitted write via
   ``Storage`` — no ``.commit()``, no ``.push_or_raise()``).

``execute_release_secrets_sync`` / ``execute_release_secrets_check`` inspect
the **CI-side** secret inventory (not the desktop ``lens deploy push``
secrets — see ``deploy/README.md`` for the distinction).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from lens.core.exceptions import LensException
from lens.core.release.config import (
    DatasetRepoConfig,
    DependentProjectConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_dependent_project_configs,
    parse_release_config,
    validate_deploy_topology,
)
from lens.core.release.version import find_lens_repo_root, parse_semver_tag


@dataclass(frozen=True)
class CiInstallationStatus:
    """Whether CI trigger files are installed and up-to-date for the leader project."""

    system: str = ""  # "github", "gitlab", "unknown"
    files_expected: tuple[str, ...] = ()
    files_present: tuple[str, ...] = ()
    all_files_match: bool = True
    files_mismatched: tuple[str, ...] = ()
    info: str = ""


@dataclass(frozen=True)
class ReleaseCheckResult:
    action: str  # "none" | "apply"
    target: str | None = None
    summary: str = ""

    # Human-readable status fields (populated by ``execute_release_check``
    # when not running in CI-only mode — mirrors ``compute_release_status``)
    enabled: bool = False
    lens_repo_url: str = ""
    requested_version: str = ""
    requested_from_commit: str = ""
    installed_version: str | None = None
    latest_available: str | None = None
    update_available: bool = False
    remote_error: str = ""

    # CI installation status for the leader project (golden-file comparison)
    ci_installation: CiInstallationStatus = field(default_factory=CiInstallationStatus)

    # Release topology: which repo is leading, its remote URL, which
    # other projects and dataset repos are part of the release.
    # Populated when enabled.
    leader_slug: str = ""
    leader_repo_url: str = ""
    dependent_projects: tuple[dict[str, str], ...] = ()
    dataset_repos: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class ReleaseApplyResult:
    lens_repo_url: str
    tag: str
    summary: str


@dataclass(frozen=True)
class ReleaseInitResult:
    ci_system: str
    files_written: tuple[str, ...]
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


# Maps CI system → list of (golden_filename, dest_relative_path)
_CI_GOLDEN_FILES: dict[str, list[tuple[str, str]]] = {
    "github": [
        ("github-release.yml", ".github/workflows/release.yml"),
        ("release.sh", "deploy/ci/release.sh"),
        ("release_secrets.py", "deploy/ci/release_secrets.py"),
    ],
    "gitlab": [
        ("gitlab-release.yml", ".gitlab-ci.yml"),
        ("release.sh", "deploy/ci/release.sh"),
        ("release_secrets.py", "deploy/ci/release_secrets.py"),
    ],
}


def _detect_ci_system(remote_url: str) -> str:
    """Detect the CI system from a git remote URL.

    Returns ``"github"``, ``"gitlab"``, or ``"unknown"``.
    """
    host = remote_url.lower()
    if "github.com" in host or "github" in host:
        return "github"
    if "gitlab.com" in host or "gitlab" in host:
        return "gitlab"
    return "unknown"


def _golden_ci_dir() -> Path | None:
    """Return the path to ``deploy/ci/`` inside the Lens repo, or ``None``."""
    root = find_lens_repo_root()
    if root is None:
        return None
    ci_dir = root / "deploy" / "ci"
    return ci_dir if ci_dir.is_dir() else None


def _check_ci_installation(
    project_root: Path,
    leader_repo_url: str,
) -> CiInstallationStatus:
    """Check whether all CI files are installed for the leader project.

    Three-part check:
      1. Detect CI system from the leader's git remote URL.
      2. Check all expected CI files (trigger + shared scripts) exist on disk.
      3. Compare file hashes against the golden templates in ``deploy/ci/``
         (only when the Lens repo is available locally).
    """
    import hashlib

    if not leader_repo_url:
        return CiInstallationStatus(info="no remote — cannot determine CI system")

    system = _detect_ci_system(leader_repo_url)
    file_map = _CI_GOLDEN_FILES.get(system)
    if file_map is None:
        return CiInstallationStatus(system=system, info="unsupported git host — CI system unknown")

    files_expected = tuple(dest for _golden, dest in file_map)
    files_present: list[str] = []
    files_mismatched: list[str] = []
    for golden_name, dest in file_map:
        dest_path = project_root / dest
        if dest_path.exists():
            files_present.append(dest)

    golden_dir = _golden_ci_dir()
    if golden_dir is not None:
        for golden_name, dest in file_map:
            if (project_root / dest).exists():
                golden_path = golden_dir / golden_name
                if golden_path.exists():
                    dest_path = project_root / dest
                    golden_hash = hashlib.sha256(golden_path.read_bytes()).hexdigest()
                    project_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()
                    if golden_hash != project_hash:
                        files_mismatched.append(dest)

    return CiInstallationStatus(
        system=system,
        files_expected=files_expected,
        files_present=tuple(files_present),
        all_files_match=len(files_mismatched) == 0,
        files_mismatched=tuple(files_mismatched),
    )


def _leader_git_remote_url(project_root: Path) -> str:
    """Return the git remote origin URL for *project_root*, or empty string."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_root, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _build_status_kwargs(
    cfg: ReleaseConfig,
    status: Any,  # ReleaseStatus from compute_release_status
    *,
    project_root: Path,
    leader_slug: str = "",
    dependent_projects: tuple[dict[str, str], ...] = (),
    dataset_repos: tuple[dict[str, str], ...] = (),
) -> dict[str, Any]:
    """Extract status and topology fields."""
    leader_repo_url = _leader_git_remote_url(project_root)
    errors: list[str] = []
    if cfg.enabled and not leader_repo_url:
        errors.append(
            f"leader {leader_slug!r} has no git remote 'origin' — "
            "CI cannot clone the project repository"
        )

    status_error = getattr(status, "remote_error", "")
    if status_error:
        errors.append(status_error)

    ci_installation = _check_ci_installation(project_root, leader_repo_url)

    return {
        "enabled": cfg.enabled,
        "lens_repo_url": cfg.lens_repo_url,
        "requested_version": cfg.requested_version.strip(),
        "requested_from_commit": cfg.requested_from_commit.strip(),
        "installed_version": getattr(status, "installed_version_str", None),
        "latest_available": getattr(status, "latest_available_str", None),
        "update_available": getattr(status, "update_available", False),
        "remote_error": " | ".join(errors),
        "leader_slug": leader_slug,
        "leader_repo_url": leader_repo_url,
        "dependent_projects": dependent_projects,
        "dataset_repos": dataset_repos,
        "ci_installation": ci_installation,
    }


def execute_release_check(
    project_root: Path,
    since: str | None = None,
) -> ReleaseCheckResult:
    """Check release status; with *since* also checks CI parent-hash match.

    Always computes and returns human-readable release status fields
    (``enabled``, ``installed_version``, ``latest_available``,
    ``update_available``, etc.) and release topology (``leader_slug``,
    ``dependent_projects``, ``dataset_repos``) for CLI display — no
    separate ``status`` call needed.

    When *since* is provided (the commit before the push range, e.g.
    ``${{ github.event.before }}``), also checks every commit in
    ``since..HEAD`` — if any of those commits has
    ``requested_from_commit`` as its parent, the result says ``"apply"``.
    Without *since* (standalone/local check), only HEAD's first parent is
    compared for the CI check.

    No git writes occur in any case.
    """
    from lens.core.release.status import compute_release_status

    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    status = compute_release_status(project_root)

    leader_slug = project_root.name
    dep_projs = tuple(
        {"name": d.name, "git_url": d.git_url, "ref": d.ref}
        for d in parse_dependent_project_configs(raw)
    )
    ds_repos = tuple(
        {"name": d.name, "git_url": d.git_url, "ref": d.ref}
        for d in parse_dataset_repo_configs(raw)
    )

    def _mk_kwargs() -> dict[str, Any]:
        return _build_status_kwargs(
            cfg, status,
            project_root=project_root,
            leader_slug=leader_slug,
            dependent_projects=dep_projs,
            dataset_repos=ds_repos,
        )

    if not cfg.enabled:
        summary = (
            "release system not enabled — add [release] enabled = true "
            "and lens_repo_url to lens.toml (see docs/configuration.md)"
        )
        return ReleaseCheckResult(
            action="none",
            summary=summary,
            **_mk_kwargs(),
        )

    requested = cfg.requested_version.strip()
    if not requested:
        return ReleaseCheckResult(
            action="none",
            summary="no version requested",
            **_mk_kwargs(),
        )

    sanity = parse_semver_tag(requested)
    if sanity is None:
        raise LensException(
            f"requested_version {requested!r} is not a valid vMAJOR.MINOR.PATCH tag"
        )

    from_commit = cfg.requested_from_commit.strip()
    if not from_commit:
        return ReleaseCheckResult(
            action="none",
            summary="requested_from_commit is empty",
            **_mk_kwargs(),
        )

    parents = _git_rev_list_parents(project_root, since)
    if from_commit in parents:
        return ReleaseCheckResult(
            action="apply",
            target=sanity.tag,
            summary=f"parent match on {from_commit}; deploy {sanity.tag}",
            **_mk_kwargs(),
        )

    return ReleaseCheckResult(
        action="none",
        summary=f"no commit in range has {from_commit} as parent",
        **_mk_kwargs(),
    )


def _resolve_latest_tag(project_root: Path, cfg: ReleaseConfig) -> str:
    """Resolve the latest available tag from the remote Lens repo.

    Used when ``apply --to`` is omitted: runs a lightweight
    ``git ls-remote`` on ``lens_repo_url``. Raises if the remote
    has no reachable tags.
    """
    from lens.core.release.version import latest_overall, list_remote_tags

    tags = list_remote_tags(cfg.lens_repo_url)
    latest = latest_overall(tags)
    if latest is None:
        raise LensException(
            f"no tags found on remote {cfg.lens_repo_url} — "
            "cannot auto-resolve latest version"
        )
    return latest.tag


def execute_release_apply(
    project_root: Path,
    target_tag: str | None = None,
) -> ReleaseApplyResult:
    """Set the target version for deployment (UI Apply button equivalent).

    When *target_tag* is ``None`` (omitted), auto-resolves to the latest
    available tag on the remote Lens repo — exactly what ``lens release
    check`` reports as latest_available.

    Writes ``requested_version`` and ``requested_from_commit`` (current
    ``HEAD``) into ``lens.toml`` via ``Storage`` — one uncommitted write,
    symmetric with :func:`execute_release_clear`.
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        raise LensException("release system is not enabled")
    url = cfg.lens_repo_url.strip()
    if not url:
        raise LensException("[release].lens_repo_url must be set")

    if target_tag is None or not target_tag.strip():
        target_tag = _resolve_latest_tag(project_root, cfg)

    normalized_tag = target_tag.strip()
    target_semver = parse_semver_tag(normalized_tag)
    if target_semver is None:
        raise LensException("--target must be a valid vMAJOR.MINOR.PATCH tag")

    req_result = execute_release_request(project_root, normalized_tag)

    return ReleaseApplyResult(
        lens_repo_url=url,
        tag=normalized_tag,
        summary=req_result.summary,
    )


def _get_head_sha(project_root: Path) -> str:
    """Return the full SHA of HEAD in *project_root*."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@dataclass(frozen=True)
class ReleaseRequestResult:
    requested_version: str
    requested_from_commit: str
    summary: str


def _set_release_field_text(
    text: str, field: str, value: str, section: str = "release",
    *,
    create_section: bool = True,
) -> str:
    """Update *field* = *value* inside the ``[section]`` block of *text*.

    Preserves all formatting, comments, and table-array syntax — avoids
    the TOML parse → modify → serialize round trip that mangles
    ``[[dependent_project]]`` entries into inline arrays.

    If the *field* line already exists inside the section it is replaced
    in place.  If it does not exist it is appended after the last field in
    the section (or immediately after the ``[section]`` header).

    When *create_section* is ``True`` (default) and the section does not
    exist, the section header + field line are appended at end of file.
    """
    lines = text.splitlines(keepends=True)
    in_section = False
    section_header = f"[{section}"
    new_line = f'{field} = "{value}"\n'

    last_field_line = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section:
                if last_field_line >= 0:
                    lines.insert(last_field_line + 1, new_line)
                else:
                    lines.insert(i, new_line)
                return "".join(lines)
            if stripped.startswith(section_header):
                in_section = True
            continue
        if in_section:
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(f"{field} "):
                lines[i] = new_line
                return "".join(lines)
            last_field_line = i

    if in_section:
        if last_field_line >= 0:
            lines.insert(last_field_line + 1, new_line)
        else:
            # Section exists but has no fields yet — insert right after header
            for j, ln in enumerate(lines):
                if ln.strip().startswith(section_header):
                    lines.insert(j + 1, new_line)
                    break
            else:
                lines.append(new_line)
        return "".join(lines)

    if not create_section:
        return text

    # Section doesn't exist — append it
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"[{section}]\n{new_line}"
    return text


def execute_release_request(project_root: Path, target_version: str) -> ReleaseRequestResult:
    """Record a human's request to deploy *target_version*.

    Validates *target_version* is a well-formed ``vMAJOR.MINOR.PATCH`` tag,
    then updates ``requested_version`` and ``requested_from_commit``
    **in-place** in ``lens.toml`` (text-edits only those two lines, no
    TOML round-trip).  Writes via ``Storage`` — **no ``.commit()``, no
    ``.push_or_raise()``**.

    This is the sole app-side mechanism of one uncommitted
    write that rides along with whatever the user's next checkpoint turns
    out to be.
    """
    from lens.core.storage import Storage

    target = target_version.strip()
    semver = parse_semver_tag(target)
    if semver is None:
        raise LensException(
            f"target_version {target!r} is not a valid vMAJOR.MINOR.PATCH tag"
        )

    head = _get_head_sha(project_root)
    lens_toml = project_root / "lens.toml"

    text = lens_toml.read_text(encoding="utf-8") if lens_toml.exists() else ""
    text = _set_release_field_text(text, "requested_version", target)
    text = _set_release_field_text(text, "requested_from_commit", head)

    storage = Storage(project_root, owner=None)
    storage.write_file_bytes(lens_toml, text.encode("utf-8"))

    return ReleaseRequestResult(
        requested_version=target,
        requested_from_commit=head,
        summary=f"release request for {target} recorded (HEAD={head[:12]})",
    )


@dataclass(frozen=True)
class ReleaseClearResult:
    summary: str


def _has_release_field_with_value(text: str, field: str) -> bool:
    """Check whether *field* is set to a non-empty value in *text*."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{field} "):
            _, _, raw = stripped.partition("=")
            val = raw.strip().strip("\"'")
            if val:
                return True
    return False


def execute_release_clear(project_root: Path) -> ReleaseClearResult:
    """Clear ``requested_version`` and ``requested_from_commit`` from ``lens.toml``.

    Text-edits only those two lines (no TOML round-trip); preserves all
    formatting, comments, and table-array syntax.  This is the inverse
    of :func:`execute_release_request` — one uncommitted write via
    ``Storage`` (no ``.commit()``, no ``.push_or_raise()``).
    """
    from lens.core.storage import Storage

    lens_toml = project_root / "lens.toml"
    text = lens_toml.read_text(encoding="utf-8") if lens_toml.exists() else ""

    if "[release]" not in text:
        return ReleaseClearResult(summary="no [release] section to clear")

    if not _has_release_field_with_value(text, "requested_version") and not _has_release_field_with_value(text, "requested_from_commit"):
        return ReleaseClearResult(summary="nothing to clear — both fields already empty")

    text = _set_release_field_text(text, "requested_version", "", create_section=False)
    text = _set_release_field_text(text, "requested_from_commit", "", create_section=False)

    storage = Storage(project_root, owner=None)
    storage.write_file_bytes(lens_toml, text.encode("utf-8"))

    return ReleaseClearResult(summary="release request cleared")


def _read_lens_toml(project_root: Path) -> dict[str, Any]:
    path = project_root / "lens.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


# ---- secrets sync ----

@dataclass(frozen=True)
class ReleaseSecretsSyncResult:
    status: str
    secrets_set: int
    summary: str
    collected_secrets: dict[str, str] = field(default_factory=lambda: {})


def _slug_to_env_key(slug: str) -> str:
    return slug.upper().replace("-", "_")


def _collect_ci_available_api_keys(
    config: dict[str, Any],
    table_key: str,
    seen: set[str],
    into: dict[str, str],
) -> None:
    """Collect API key env vars from ``[[{table_key}]]``, CI-safe (additive-only).

    Unlike the desktop deploy path which raises on missing env vars, this
    simply skips keys that aren't set in the CI environment.
    """
    raw_list = config.get(table_key, [])
    entries: list[Any] = cast(list[Any], raw_list) if isinstance(raw_list, list) else []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        env_name = entry.get("api_key_env")
        if not isinstance(env_name, str) or env_name in seen:
            continue
        seen.add(env_name)
        value = os.environ.get(env_name)
        if value:
            into[env_name] = value


def _get_git_remote_url(project_root: Path) -> str:
    """Return the remote URL for *project_root*."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LensException(
            f"failed to get git remote URL for {project_root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _git_clone(git_url: str, dest: Path, ref: str = "main", deploy_key: str | None = None) -> None:
    """Clone *git_url* to *dest* and check out *ref*."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if git_url.startswith("git@") or git_url.startswith("ssh://"):
        ssh_cmd = "ssh -o StrictHostKeyChecking=accept-new"
        if deploy_key:
            key_dir = Path(tempfile.mkdtemp(prefix="lens-deploy-key-"))
            key_file = key_dir / "id"
            key_file.write_text(deploy_key)
            key_file.chmod(0o600)
            ssh_cmd += f" -i {key_file}"
        env["GIT_SSH_COMMAND"] = ssh_cmd

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, git_url, str(dest)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise LensException(
            f"git clone {git_url} failed: {result.stderr.strip()}"
        )


def _fly_secrets_set(fly_app: str, secrets: dict[str, str]) -> None:
    """Push *secrets* to the Fly app via ``fly secrets set``."""
    args = ["flyctl", "secrets", "set", "--app", fly_app]
    for key, value in secrets.items():
        args.append(f"{key}={value}")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise LensException(
            f"fly secrets set failed: {result.stderr.strip() or result.stdout.strip()}"
        )


def _detect_lens_repo_url(project_root: Path) -> str | None:
    """Try to auto-detect the Lens repo URL.

    Checks the Lens package's own git remote (useful for Lens developers),
    then falls back to the leader project's own remote.  Returns ``None``
    when neither yields a usable URL.
    """
    from lens.core.release.version import find_lens_repo_root

    lens_root = find_lens_repo_root()
    if lens_root is not None:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=lens_root, capture_output=True, text=True,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url:
                    return url
        except Exception:
            pass

    leader_url = _leader_git_remote_url(project_root)
    if leader_url:
        return leader_url

    return None


def _append_table_array_entry(text: str, table_name: str, fields: dict[str, str]) -> str:
    """Append a ``[[table_name]]`` entry to *text*.

    Each key-value pair from *fields* is written as ``key = "value"``.
    The entry is appended at the end of the file, preserving all existing
    content, formatting, and comments.  Returns the modified text.
    """
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"\n[[{table_name}]]\n"
    for key, value in fields.items():
        text += f'{key} = "{value}"\n'
    return text


def _discover_dependent_projects(
    project_root: Path,
    leader_slug: str | None = None,
) -> list[dict[str, str]]:
    """Scan for sibling projects that could be ``[[dependent_project]]`` entries.

    Looks in the parent of *project_root* for other directories containing
    ``lens.toml`` that are valid git repos with an SSH remote.  The leader
    project itself (matched by *leader_slug*, defaulting to
    ``project_root.name``) is excluded.

    Returns entries suitable for directly writing as
    ``[[dependent_project]]``.  Returns an empty list when no parent
    directory exists or no qualifying siblings are found.
    """

    parent = project_root.parent
    if leader_slug is None:
        leader_slug = project_root.name

    result: list[dict[str, str]] = []
    if not parent.is_dir():
        return result

    for child in sorted(parent.iterdir()):
        if not child.is_dir():
            continue
        if child.name == leader_slug:
            continue
        if not (child / "lens.toml").exists():
            continue

        try:
            remote_url = _get_git_remote_url(child)
        except LensException:
            continue

        try:
            from lens.core.git_ssh_remote import parse_git_ssh_remote
            parse_git_ssh_remote(remote_url)
        except ValueError:
            continue

        result.append({
            "name": child.name,
            "git_url": remote_url,
            "ref": "main",
        })

    return result


def _discover_dataset_repos(
    project_root: Path,
    existing_names: set[str] | None = None,
) -> list[dict[str, str]]:
    """Find non-bundled datasets that are NOT yet configured and resolve them.

    For each dataset declared in ``[project] datasets`` of *project_root*,
    skips those already listed in *existing_names* (already present in
    ``[[dataset_repo]]``) and skips datasets bundled with Lens (under
    ``datasets/``).  Resolves the remainder to a local path and reads the
    git remote URL.

    The release system clones dataset repos at runtime (unlike the desktop
    deploy flow which bundles them into the Docker image) — so every
    non-bundled dataset must have a reachable git remote.  Both SSH and
    HTTPS remotes are accepted; private repos additionally need a deploy
    key configured separately via ``DATASET_REPO_DEPLOY_KEY_<NAME>``.

    Returns entries suitable for ``[[dataset_repo]]``.  Raises
    :class:`LensException` when a non-bundled dataset cannot be found on
    disk or has no git remote.
    """
    skip_names: set[str] = existing_names if existing_names is not None else set()
    from lens.core.project import datasets_root, get_selected_datasets, resolve_dataset_path

    ds_root = datasets_root().resolve()
    selected = get_selected_datasets(project_root)
    result: list[dict[str, str]] = []

    for name in selected:
        if name in skip_names:
            continue
        bundled = ds_root / name
        if bundled.is_dir():
            continue

        path = resolve_dataset_path(project_root, name)
        if path is None:
            raise LensException(
                f"dataset '{name}' not found — cannot configure for release. "
                f"Checked {ds_root / name}, sibling of Lens repo, and lens.local.toml"
            )

        remote_url = _get_git_remote_url(path)
        if not remote_url:
            raise LensException(
                f"dataset '{name}' at {path} has no git remote 'origin' — "
                "a remote is required for release deployment (dataset must be "
                "clone-able at container boot time)"
            )

        from lens.core.release.config import validate_git_url
        err = validate_git_url(remote_url)
        if err:
            raise LensException(
                f"dataset '{name}' remote {remote_url} has an invalid git URL: {err}"
            )

        result.append({
            "name": name,
            "git_url": remote_url,
            "ref": "main",
        })

    return result


def execute_release_init(
    project_root: Path,
    *,
    lens_repo_url: str | None = None,
    leader: bool = False,
) -> ReleaseInitResult:
    """Install CI trigger files and activate the release system for *project_root*.

    Performs a full release-system bootstrap:

    1. **Configure** ``[release]`` — enables the section, sets
       ``lens_repo_url``, and designates the leader (``app_leader = true``)
       when requested.
    2. **Discover dependent projects** — scans for sibling ``lens.toml``
       directories, validates they have SSH git remotes, and writes
       ``[[dependent_project]]`` entries (skipping already-configured ones).
    3. **Discover dataset repos** — finds non-bundled datasets referenced
       by the project, resolves their paths, validates they have SSH git
       remotes, and writes ``[[dataset_repo]]`` entries (skipping
       already-configured ones).
    4. **Install CI files** — copies the provider-specific CI template
       and shared scripts from Lens's golden templates.

    Raises :class:`LensException` when any validation step fails or the
    golden CI templates are not available (Lens installed from PyPI
    without a local checkout).
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)

    effective_lens_repo_url: str = ""
    if lens_repo_url:
        effective_lens_repo_url = lens_repo_url.strip()
    elif cfg.lens_repo_url.strip():
        effective_lens_repo_url = cfg.lens_repo_url.strip()
    else:
        detected = _detect_lens_repo_url(project_root)
        if detected:
            effective_lens_repo_url = detected
        else:
            raise LensException(
                "lens_repo_url is required — pass --lens-repo-url or "
                "set [release] lens_repo_url in lens.toml"
            )

    # ---- 1. Write [release] config changes ----
    lens_toml = project_root / "lens.toml"
    text = lens_toml.read_text(encoding="utf-8") if lens_toml.exists() else ""
    modified = False

    if not cfg.enabled:
        text = _set_release_field_text(text, "enabled", "true")
        modified = True

    if not cfg.lens_repo_url.strip() and effective_lens_repo_url:
        text = _set_release_field_text(text, "lens_repo_url", effective_lens_repo_url)
        modified = True

    if leader and not cfg.app_leader:
        text = _set_release_field_text(text, "app_leader", "true")
        modified = True

    # ---- 2. Write [[dependent_project]] entries ----
    existing_deps = {d.name for d in parse_dependent_project_configs(raw)}
    discovered_deps = _discover_dependent_projects(
        project_root, leader_slug=project_root.name if leader else None,
    )

    for dep in discovered_deps:
        if dep["name"] not in existing_deps:
            text = _append_table_array_entry(text, "dependent_project", dep)
            modified = True

    # ---- 3. Write [[dataset_repo]] entries ----
    existing_ds_config = {d.name: d for d in parse_dataset_repo_configs(raw)}
    discovered_ds = _discover_dataset_repos(project_root)

    new_ds: list[dict[str, str]] = []
    for dse in discovered_ds:
        if dse["name"] not in existing_ds_config:
            text = _append_table_array_entry(text, "dataset_repo", dse)
            new_ds.append(dse)
            modified = True

    # ---- Persist lens.toml changes ----
    if modified:
        from lens.core.storage import Storage

        storage = Storage(project_root, owner=None)
        storage.write_file_bytes(lens_toml, text.encode("utf-8"))

    # ---- 4. Install CI files ----
    leader_repo_url = _leader_git_remote_url(project_root)
    if not leader_repo_url:
        raise LensException(
            "cannot determine CI system — leader has no git remote 'origin'"
        )

    system = _detect_ci_system(leader_repo_url)
    if system == "unknown":
        raise LensException(
            f"unsupported CI system for remote {leader_repo_url} — "
            "cannot install CI files"
        )

    golden_dir = _golden_ci_dir()
    if golden_dir is None:
        raise LensException(
            "golden CI templates not available — Lens must be installed "
            "from a git checkout"
        )

    files_written: list[str] = []
    file_map = _CI_GOLDEN_FILES[system]
    for golden_name, dest in file_map:
        src = golden_dir / golden_name
        dst = project_root / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files_written.append(str(dst.relative_to(project_root)))
    files_written.sort()

    # ---- Gather all dataset repos for display ----
    all_ds: list[dict[str, str]] = [
        {"name": d.name, "git_url": d.git_url, "ref": d.ref}
        for d in existing_ds_config.values()
    ]
    all_ds.extend(new_ds)

    # ---- Check for fly.toml ----
    fly_toml = project_root / "fly.toml"
    has_fly_toml = fly_toml.is_file()
    if not has_fly_toml:
        has_fly_toml = (project_root.parent / "fly.toml").is_file()

    # ---- Build summary ----
    lines: list[str] = [
        f"CI files installed for {system}:",
    ]
    for f in files_written:
        lines.append(f"  ✓ {f}")
    lines.append("")

    # Topology
    if leader:
        lines.append(f"Project:   {project_root.name}  (release leader)")
    else:
        lines.append(f"Project:   {project_root.name}")
    if discovered_deps:
        lines.append("Dependents:")
        for dep in discovered_deps:
            lines.append(f"  • {dep['name']}  ({dep['git_url']})")

    # Release config
    lines.append("")
    if modified and effective_lens_repo_url:
        lines.append(f"[release] enabled  (repo: {effective_lens_repo_url})")
    else:
        lines.append("[release] already configured")

    # Dataset repos
    for dse in all_ds:
        name = dse["name"]
        url = dse["git_url"]
        status = "new" if any(n["name"] == name for n in new_ds) else "existing"
        lines.append("")
        lines.append(f"Dataset repo:  {name}")
        lines.append(f"  url: {url}")
        lines.append(f"  ref: {dse['ref']}  ({status})")
        if url.startswith("https://"):
            lines.append(
                "  ⚠ HTTPS — switch to SSH or confirm it's a public repo "
                "(edit lens.toml [[dataset_repo]])"
            )

    # Deploy status
    lines.append("")
    if has_fly_toml:
        lines.append("fly.toml:    found")
    else:
        lines.append("fly.toml:    not found  (run 'lens deploy init' first)")
        lines.append("             The release system clones dataset repos at runtime without")
        lines.append("             S3 — fly.toml and a Fly.io app are still needed for serving")

    lines.append("")
    lines.append("Next steps:")
    if not has_fly_toml:
        lines.append("  - lens deploy init  --app <name> --region <region> --user <user> --password")
    lines.append("  - lens release check  (verify configuration)")
    lines.append("  - lens release secrets check --fly (verify secrets)")

    return ReleaseInitResult(
        ci_system=system,
        files_written=tuple(files_written),
        summary="\n".join(lines),
    )


def execute_release_secrets_sync(
    project_root: Path,
    fly_app: str,
    dry_run: bool = False,
) -> ReleaseSecretsSyncResult:
    """Discover topology, collect CI-available secrets, push to Fly.

    Reads the leader project's ``lens.toml``, parses ``[[dependent_project]]``,
    clones each dependent (to read their ``lens.toml`` for API key config),
    and collects all secrets that are actually set in the CI environment.

    **Additive-only semantics**: only secrets whose env vars are non-empty
    in CI are included.  Nothing is unset or deleted on Fly.

    When *dry_run* is ``True``, skips the ``fly secrets set`` call and
    returns the collected secrets in ``collected_secrets`` for inspection
    (useful in tests).
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        raise LensException("release system is not enabled")

    dependents = parse_dependent_project_configs(raw)
    leader_slug = project_root.name

    all_projects: list[tuple[str, Path, dict[str, Any]]] = [
        (leader_slug, project_root, raw),
    ]
    temp_clone_dirs: list[Path] = []

    try:
        for dep in dependents:
            clone_dir = Path(tempfile.mkdtemp(prefix=f"lens-secrets-{dep.name}-")) / dep.name
            temp_clone_dirs.append(clone_dir.parent)
            deploy_key = os.environ.get(f"GIT_REPO_DEPLOY_KEY_{dep.name.upper().replace('-', '_')}")
            try:
                _git_clone(dep.git_url, clone_dir, dep.ref, deploy_key=deploy_key)
            except LensException:
                print(f"  [skipped] could not clone dependent '{dep.name}' — deploy key not in CI env", file=sys.stderr)
                continue
            dep_raw = _read_lens_toml(clone_dir)
            all_projects.append((dep.name, clone_dir, dep_raw))

        secrets: dict[str, str] = {}
        seen_api_keys: set[str] = set()

        for _slug, _proj_root, proj_raw in all_projects:
            _collect_ci_available_api_keys(proj_raw, "llm", seen_api_keys, secrets)
            _collect_ci_available_api_keys(proj_raw, "image", seen_api_keys, secrets)
            _collect_ci_available_api_keys(proj_raw, "speech", seen_api_keys, secrets)

        for slug, proj_root, _proj_raw in all_projects:
            env_key = _slug_to_env_key(slug)
            deploy_key_var = f"GIT_REPO_DEPLOY_KEY_{env_key}"
            val = os.environ.get(deploy_key_var)
            if val:
                secrets[deploy_key_var] = val

        for slug, proj_root, _proj_raw in all_projects:
            env_key = _slug_to_env_key(slug)
            if slug == leader_slug:
                url = _get_git_remote_url(proj_root)
            else:
                dep = next(d for d in dependents if d.name == slug)
                url = dep.git_url
            secrets[f"PROJECT_REPO_URL_{env_key}"] = url

        seen_datasets: set[str] = set()
        for _slug, _proj_root, proj_raw in all_projects:
            for repo in parse_dataset_repo_configs(proj_raw):
                if repo.name in seen_datasets:
                    continue
                seen_datasets.add(repo.name)
                env_key = repo.name.upper().replace("-", "_")
                var_name = f"DATASET_REPO_DEPLOY_KEY_{env_key}"
                val = os.environ.get(var_name)
                if val:
                    secrets[var_name] = val

        slugs = [leader_slug] + [d.name for d in dependents]
        secrets["LENS_PROJECT_SLUGS"] = ",".join(slugs)

        if not dry_run and secrets:
            _fly_secrets_set(fly_app, secrets)

        return ReleaseSecretsSyncResult(
            status="ok",
            secrets_set=len(secrets),
            summary=f"synced {len(secrets)} secrets to Fly app {fly_app}",
            collected_secrets=secrets,
        )
    finally:
        for tmp_dir in temp_clone_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---- secrets check ----

@dataclass(frozen=True)
class SecretRequirement:
    name: str
    source: str
    set_in_env: bool
    set_on_fly: bool | None = None


@dataclass(frozen=True)
class ReleaseSecretsCheckResult:
    leader_slug: str
    fly_app: str | None
    project_slugs: list[str]
    dependent_projects: list[DependentProjectConfig]
    dataset_repos: list[DatasetRepoConfig]
    secrets: list[SecretRequirement]


def _read_fly_app(project_root: Path) -> str | None:
    """Read the Fly app name from ``fly.toml`` in *project_root*, if present."""
    fly_toml = project_root / "fly.toml"
    if not fly_toml.exists():
        return None
    try:
        with fly_toml.open("rb") as f:
            cfg: dict[str, Any] = tomllib.load(f)
        app = cfg.get("app")
        return str(app) if isinstance(app, str) and app.strip() else None
    except Exception:
        return None


def _list_fly_secrets(fly_app: str) -> set[str]:
    """Return the set of secret names set on the Fly app, or empty set on failure."""
    try:
        result = subprocess.run(
            ["flyctl", "secrets", "list", "--app", fly_app],
            capture_output=True, text=True, check=True,
        )
        names: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if parts and not parts[0].startswith("NAME"):
                names.add(parts[0])
        return names
    except Exception:
        return set()


def execute_release_secrets_check(
    project_root: Path,
    *,
    check_fly: bool = False,
) -> ReleaseSecretsCheckResult:
    """Scan topology and report every secret the release system needs.

    Discovers the leader slug, ``[[dependent_project]]`` entries,
    ``[[dataset_repo]]`` entries, and API key env vars from the leader's
    ``lens.toml`` (and from cloned dependents when any are configured).

    When *check_fly* is ``True`` and a ``fly.toml`` is found, also checks
    which secrets are already set on the Fly app.
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        raise LensException("release system is not enabled")

    dependents = parse_dependent_project_configs(raw)
    dataset_repos = parse_dataset_repo_configs(raw)
    leader_slug = project_root.name
    fly_app = _read_fly_app(project_root)

    fly_secrets: set[str] = set()
    if check_fly and fly_app:
        fly_secrets = _list_fly_secrets(fly_app)

    secrets: list[SecretRequirement] = []
    seen_api_keys: set[str] = set()

    # Collect project configs (leader + cloned dependents)
    all_configs: list[tuple[str, dict[str, Any]]] = [(leader_slug, raw)]
    temp_clone_dirs: list[Path] = []

    try:
        for dep in dependents:
            clone_dir = Path(tempfile.mkdtemp(prefix=f"lens-secrets-{dep.name}-")) / dep.name
            temp_clone_dirs.append(clone_dir.parent)
            deploy_key = os.environ.get(f"GIT_REPO_DEPLOY_KEY_{dep.name.upper().replace('-', '_')}")
            try:
                _git_clone(dep.git_url, clone_dir, dep.ref, deploy_key=deploy_key)
            except LensException:
                print(f"  [skipped] could not clone dependent '{dep.name}' — deploy key not in CI env", file=sys.stderr)
                continue
            dep_raw = _read_lens_toml(clone_dir)
            all_configs.append((dep.name, dep_raw))

        # 1. API key env vars from all project configs
        for slug, config in all_configs:
            for table_key in ("llm", "image", "speech"):
                raw_list = config.get(table_key, [])
                entries: list[Any] = cast(list[Any], raw_list) if isinstance(raw_list, list) else []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry_cfg: dict[str, Any] = cast(dict[str, Any], entry)
                    env_name: str | None = cast(str | None, entry_cfg.get("api_key_env"))
                    if not isinstance(env_name, str) or env_name in seen_api_keys:
                        continue
                    seen_api_keys.add(env_name)
                    provider: str | None = cast(str | None, entry_cfg.get("provider", "?"))
                    secrets.append(SecretRequirement(
                        name=env_name,
                        source=f"{table_key}: {provider}" + (f" ({slug})" if slug != leader_slug else ""),
                        set_in_env=env_name in os.environ,
                        set_on_fly=env_name in fly_secrets if check_fly else None,
                    ))

        # 2. Project deploy keys (leader + dependents)
        for slug, _config in all_configs:
            env_key = _slug_to_env_key(slug)
            key_var = f"GIT_REPO_DEPLOY_KEY_{env_key}"
            tag = "project" if slug == leader_slug else "dependent_project"
            secrets.append(SecretRequirement(
                name=key_var,
                source=f"{tag}: {slug}",
                set_in_env=key_var in os.environ,
                set_on_fly=key_var in fly_secrets if check_fly else None,
            ))

        # 3. Dataset repo deploy keys
        for repo in dataset_repos:
            ds_env_key = repo.name.upper().replace("-", "_")
            ds_key_var = f"DATASET_REPO_DEPLOY_KEY_{ds_env_key}"
            secrets.append(SecretRequirement(
                name=ds_key_var,
                source=f"dataset_repo: {repo.name}",
                set_in_env=ds_key_var in os.environ,
                set_on_fly=ds_key_var in fly_secrets if check_fly else None,
            ))

        # 4. FLY_API_TOKEN (required by flyctl)
        secrets.append(SecretRequirement(
            name="FLY_API_TOKEN",
            source="flyctl deploy auth",
            set_in_env="FLY_API_TOKEN" in os.environ,
        ))

        # 5. Caddy basic auth (set by lens deploy init)
        for caddy_name in ("CADDY_BASIC_AUTH_USER", "CADDY_BASIC_AUTH_HASH"):
            secrets.append(SecretRequirement(
                name=caddy_name,
                source="Caddy reverse-proxy auth",
                set_in_env=caddy_name in os.environ,
                set_on_fly=caddy_name in fly_secrets if check_fly else None,
            ))

        project_slugs = [leader_slug] + [d.name for d in dependents]

        return ReleaseSecretsCheckResult(
            leader_slug=leader_slug,
            fly_app=fly_app,
            project_slugs=project_slugs,
            dependent_projects=dependents,
            dataset_repos=dataset_repos,
            secrets=secrets,
        )
    finally:
        for tmp_dir in temp_clone_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)
