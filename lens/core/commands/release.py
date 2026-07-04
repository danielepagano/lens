"""Core helpers for the release decision engine (`lens release`).

Per decision #4 in docs/release-system.md: CI's job is a single, stateless,
read-only parent-hash check. Nothing in this module writes to git, *except*
``execute_release_request`` which the app uses to record a human's deploy
request (decision #1/#3 — one uncommitted write, never a commit/push).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
import tomli_w

from lens.core.exceptions import LensException
from lens.core.release.config import (
    DatasetRepoConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_dependent_project_configs,
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


def execute_release_request(project_root: Path, target_version: str) -> ReleaseRequestResult:
    """Record a human's request to deploy *target_version*.

    Validates *target_version* is a well-formed ``vMAJOR.MINOR.PATCH`` tag,
    reads the current ``lens.toml``, sets ``requested_version`` **and**
    ``requested_from_commit`` (the current ``HEAD`` hash), and writes it
    back via ``Storage`` — **no ``.commit()``, no ``.push_or_raise()``**.

    This is the sole app-side mechanism of decision #3: one uncommitted
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

    raw: dict[str, Any] = {}
    lens_toml = project_root / "lens.toml"
    if lens_toml.exists():
        with lens_toml.open("rb") as f:
            raw = tomllib.load(f)

    release_section = raw.get("release")
    if not isinstance(release_section, dict):
        release_section = {}
    release_section["requested_version"] = target
    release_section["requested_from_commit"] = head
    raw["release"] = release_section

    buf = io.BytesIO()
    tomli_w.dump(raw, buf)

    storage = Storage(project_root, owner=None)
    storage.write_file_bytes(lens_toml, buf.getvalue())

    return ReleaseRequestResult(
        requested_version=target,
        requested_from_commit=head,
        summary=f"release request for {target} recorded (HEAD={head[:12]})",
    )


@dataclass(frozen=True)
class ReleaseClearResult:
    summary: str


def execute_release_clear(project_root: Path) -> ReleaseClearResult:
    """Clear ``requested_version`` and ``requested_from_commit`` from ``lens.toml``.

    This is the inverse of :func:`execute_release_request` — it allows a user
    to cancel a pending deploy request.  Like ``request``, this is one
    uncommitted write via ``Storage`` (no ``.commit()``, no
    ``.push_or_raise()``).
    """
    from lens.core.storage import Storage

    raw: dict[str, Any] = {}
    lens_toml = project_root / "lens.toml"
    if lens_toml.exists():
        with lens_toml.open("rb") as f:
            raw = tomllib.load(f)

    release_section = raw.get("release")
    if not isinstance(release_section, dict):
        return ReleaseClearResult(summary="no [release] section to clear")
    rs = cast("dict[str, Any]", release_section)

    if not rs.get("requested_version") and not rs.get("requested_from_commit"):
        return ReleaseClearResult(summary="nothing to clear — both fields already empty")

    rs["requested_version"] = ""
    rs["requested_from_commit"] = ""
    raw["release"] = rs

    buf = io.BytesIO()
    tomli_w.dump(raw, buf)

    storage = Storage(project_root, owner=None)
    storage.write_file_bytes(lens_toml, buf.getvalue())

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


def _git_clone(git_url: str, dest: Path, ref: str = "main") -> None:
    """Clone *git_url* to *dest* and check out *ref*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, git_url, str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LensException(
            f"git clone {git_url} failed: {result.stderr.strip()}"
        )


def _fly_secrets_set(fly_app: str, secrets: dict[str, str]) -> None:
    """Push *secrets* to the Fly app via ``fly secrets set``."""
    args = ["fly", "secrets", "set", "--app", fly_app]
    for key, value in secrets.items():
        args.append(f"{key}={value}")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise LensException(
            f"fly secrets set failed: {result.stderr.strip() or result.stdout.strip()}"
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
            _git_clone(dep.git_url, clone_dir, dep.ref)
            dep_raw = _read_lens_toml(clone_dir)
            all_projects.append((dep.name, clone_dir, dep_raw))
            temp_clone_dirs.append(clone_dir.parent)

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
