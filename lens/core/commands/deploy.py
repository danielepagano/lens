"""Core logic for Fly.io deployment management."""

from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, cast

import bcrypt  # type: ignore[import-untyped]

from lens.core.exceptions import LensException
from lens.core.git_ssh_remote import parse_git_ssh_remote
from lens.core.project import (
    datasets_root,
    get_selected_datasets,
    require_s3_mount_when_configured,
    resolve_dataset_path,
)
from lens.core.release.config import (
    DatasetRepoConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_dependent_project_configs,
    parse_release_config,
    validate_deploy_topology,
)
from lens.core.release.version import compute_local_version
from lens.core.storage import Storage

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class FlyDeployBuildMode(str, enum.Enum):
    """How ``lens deploy push`` invokes ``fly deploy``."""

    fly = "fly"
    depot = "depot"
    local = "local"


# Single and multi-project deployments share one fly.toml format.
# Single-project is just the multi-project case with one slug; the fly.toml
# lives inside the project directory, and LENS_PROJECT_SLUGS contains that
# one slug.
_FLY_TOML_TEMPLATE = """\
app = "{app_name}"
primary_region = "{region}"

[env]
  LENS_CLOUD_DEPLOYED = "1"
  LENS_PROJECT_DIR = "/data/repos"
  LENS_PROJECT_SLUGS = "{slugs}"
  LENS_PORT = "8000"
  CADDY_PORT = "8080"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "suspend"
  auto_start_machines = true
  min_machines_running = 1

[[mounts]]
  source = "lens_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
"""

_AWS_ENV_VARS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "AWS_DEFAULT_REGION",
]


def _slug_to_env_key(slug: str) -> str:
    """Convert a project slug to a valid env var suffix.

    Example: ``my-project`` → ``MY_PROJECT``
    """
    return slug.upper().replace("-", "_")


def read_lens_toml(project_root: Path) -> dict[str, Any]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise LensException(f"{lens_toml} not found")
    with lens_toml.open("rb") as f:
        return tomllib.load(f)


def _read_fly_toml(fly_toml: Path) -> dict[str, Any]:
    if not fly_toml.exists():
        raise LensException("fly.toml not found — run 'lens deploy init' first")
    with fly_toml.open("rb") as f:
        return tomllib.load(f)


def get_fly_app_name(fly_toml: Path) -> str:
    config = _read_fly_toml(fly_toml)
    app = config.get("app")
    if not isinstance(app, str) or not app:
        raise LensException("fly.toml is missing the 'app' field")
    return app


def get_slugs(fly_toml: Path) -> list[str]:
    """Return the current project slugs from fly.toml."""
    config = _read_fly_toml(fly_toml)
    env_section = config.get("env", {})
    raw = env_section.get("LENS_PROJECT_SLUGS", "")
    return [s for s in raw.split(",") if s]


def _update_slugs_in_fly_toml(fly_toml: Path, new_slugs: list[str]) -> None:
    """Update the LENS_PROJECT_SLUGS line in fly.toml in place."""
    content = fly_toml.read_text()
    updated = re.sub(
        r'(LENS_PROJECT_SLUGS\s*=\s*")[^"]*(")',
        f'\\g<1>{",".join(new_slugs)}\\g<2>',
        content,
    )
    fly_toml.write_text(updated)


def _get_s3_bucket(uri: str) -> str:
    """Extract the bucket name from an ``s3://bucket/path`` URI."""
    without_scheme = uri[len("s3://"):]
    return without_scheme.split("/")[0]


def _collect_table_array_api_key_secrets(
    config: dict[str, Any],
    table_key: str,
    seen: set[str],
) -> dict[str, str]:
    """Return API key env secrets from ``[[{table_key}]]`` blocks in *config*.

    *seen* is updated in place to avoid duplicate env var names across blocks
    and projects (same name in ``llm`` and ``image`` is set once).
    """
    secrets: dict[str, str] = {}
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
        if not value:
            raise LensException(
                f"lens.toml [[{table_key}]] requires {env_name} "
                f"but it is not set in your environment"
            )
        secrets[env_name] = value
    return secrets


def _collect_llm_secrets(config: dict[str, Any], seen: set[str]) -> dict[str, str]:
    """Return LLM API key secrets from ``[[llm]]`` entries."""
    return _collect_table_array_api_key_secrets(config, "llm", seen)


def _collect_image_secrets(config: dict[str, Any], seen: set[str]) -> dict[str, str]:
    """Return image backend API key secrets from ``[[image]]`` entries."""
    return _collect_table_array_api_key_secrets(config, "image", seen)


def _collect_speech_secrets(config: dict[str, Any], seen: set[str]) -> dict[str, str]:
    """Return speech (TTS) API key secrets from ``[[speech]]`` entries."""
    return _collect_table_array_api_key_secrets(config, "speech", seen)


def _append_project_api_key_secrets(
    config: dict[str, Any],
    into: dict[str, str],
    seen: set[str],
) -> None:
    """Merge ``[[llm]]``, ``[[image]]``, and ``[[speech]]`` API keys from *config*."""
    into.update(_collect_llm_secrets(config, seen))
    into.update(_collect_image_secrets(config, seen))
    into.update(_collect_speech_secrets(config, seen))


def collect_all_project_api_key_secrets(
    projects: list[tuple[str, Path, Path]],
) -> dict[str, str]:
    """LLM + image + speech ``api_key_env`` values for all projects, deduplicated."""
    seen: set[str] = set()
    out: dict[str, str] = {}
    for _slug, _git_root, project_root in projects:
        config = read_lens_toml(project_root)
        _append_project_api_key_secrets(config, out, seen)
    return out


def collect_api_key_secrets_for_lens_config(config: dict[str, Any]) -> dict[str, str]:
    """Resolve ``[[llm]]`` / ``[[image]]`` / ``[[speech]]`` ``api_key_env`` vs environment.

    Single parsed ``lens.toml`` top-level mapping (e.g. from tests).
    """
    seen: set[str] = set()
    out: dict[str, str] = {}
    _append_project_api_key_secrets(config, out, seen)
    return out


def _validate_project_for_deploy(slug: str, project_root: Path, git_root: Path) -> str:
    """Validate a project is deployable.

    Checks:
    - git remote ``origin`` is an SSH URL
    - ``mount_point`` (if set) is an S3 URI, not a local path

    Returns the SSH remote URL.
    Raises :class:`LensException` if any check fails.
    """
    storage = Storage(git_root)
    try:
        remote_url = storage.get_remote_url()
    except Exception as exc:
        raise LensException(f"project '{slug}': cannot read git remote 'origin': {exc}") from exc

    try:
        parse_git_ssh_remote(remote_url)
    except ValueError as exc:
        raise LensException(f"project '{slug}': {exc}") from exc

    require_s3_mount_when_configured(project_root, slug=slug, context="deploy")

    return remote_url


def resolve_project_root_for_slug(deploy_dir: Path, slug: str) -> Path:
    """Resolve a single project's root directory for *slug* relative to ``deploy_dir``.

    Tries, in order:

    1. ``deploy_dir`` itself, when its directory name is *slug* and it has its
       own ``lens.toml`` — single-project mode, or the release leader's own
       slug in the leader-colocated multi-project topology (fly.toml lives
       inside the leader's project directory; see "Multi-project deployments"
       in ``deploy/README.md``).
    2. ``deploy_dir / slug`` — the classic multi-project topology, where
       ``fly.toml`` lives in a bare parent-of-projects directory and every
       project is an immediate child of it.
    3. ``deploy_dir.parent / slug`` — sibling ("cousin") resolution for the
       leader-colocated topology: other served projects live alongside the
       leader, not underneath it.

    Raises :class:`LensException` if none of these has a ``lens.toml``.
    """
    if deploy_dir.name == slug and (deploy_dir / "lens.toml").exists():
        return deploy_dir

    child = deploy_dir / slug
    if (child / "lens.toml").exists():
        return child

    cousin = deploy_dir.parent / slug
    if (cousin / "lens.toml").exists():
        return cousin

    raise LensException(
        f"project '{slug}': no lens.toml found at {child} or {cousin}"
    )


def build_projects(deploy_dir: Path, slugs: list[str]) -> list[tuple[str, Path, Path]]:
    """Return ``[(slug, git_root, project_root), ...]`` for the given slugs.

    Each slug's project root is resolved via
    :func:`resolve_project_root_for_slug`, which supports both the bare
    parent-of-projects ``fly.toml`` topology and the leader-colocated
    topology (fly.toml inside the release leader's own project directory,
    siblings resolved as ``deploy_dir.parent / slug``).
    """
    from lens.core.project import find_git_root_from

    projects: list[tuple[str, Path, Path]] = []
    for slug in slugs:
        project_root = resolve_project_root_for_slug(deploy_dir, slug)
        try:
            git_root = find_git_root_from(project_root)
        except RuntimeError as exc:
            raise LensException(f"project '{slug}': {exc}") from exc
        projects.append((slug, git_root, project_root))
    return projects


def find_colocated_fly_toml(start: Path) -> Path | None:
    """Return the ``fly.toml`` path in an immediate child of *start*, if any.

    Supports the leader-colocated multi-project topology, where ``fly.toml``
    lives inside one served project's own directory (the release leader)
    instead of a separate bare parent-of-projects directory — see
    "Multi-project deployments" in ``deploy/README.md``. Scans one level
    deep only, matching the same convention as
    :func:`lens.core.project.discover_projects`. Returns ``None`` if *start*
    is not a directory or no child qualifies.
    """
    if not start.is_dir():
        return None
    for child in sorted(start.iterdir()):
        if child.is_dir() and (child / "lens.toml").exists() and (child / "fly.toml").exists():
            return child / "fly.toml"
    return None


def resolve_deploy_dir(cwd: Path) -> Path:
    """Resolve the directory ``lens deploy push``/``add``/``remove`` should act on.

    Tries, in order:

    1. *cwd* itself has ``fly.toml`` — the bare parent-of-projects directory,
       or a single-project / leader-project directory that colocates
       ``fly.toml`` with its own ``lens.toml``.
    2. *cwd* is inside a project (``lens.toml`` at *cwd* or an ancestor) whose
       root also has ``fly.toml`` — running from a subdirectory of a
       single-project deployment.
    3. An immediate child of *cwd* colocates ``lens.toml`` + ``fly.toml`` —
       running from the grandparent directory of a leader-colocated
       multi-project deployment.

    Raises :class:`LensException` if none apply.
    """
    cwd = cwd.resolve()
    if (cwd / "fly.toml").exists():
        return cwd

    from lens.core.project import find_project_root_if_any

    project_root = find_project_root_if_any(cwd)
    if project_root is not None and (project_root / "fly.toml").exists():
        return project_root

    fly_toml = find_colocated_fly_toml(cwd)
    if fly_toml is not None:
        return fly_toml.parent

    raise LensException(
        "no fly.toml found at this directory, an ancestor project, or an "
        "immediate leader-project subdirectory — run 'lens deploy init' first"
    )


def collect_dataset_repo_deploy_key_secrets(
    projects: list[tuple[str, Path, Path]],
) -> dict[str, str]:
    """Collect ``DATASET_REPO_DEPLOY_KEY_<NAME>`` secrets from the local environment.

    For each unique ``[[dataset_repo]]`` name across all *projects*, checks if
    ``DATASET_REPO_DEPLOY_KEY_<ENV_KEY>`` is set in the environment.  If found,
    it's included — if not, the repo is assumed public (no deploy key needed).
    Returns an empty dict when no dataset repos are configured.
    """
    secrets: dict[str, str] = {}
    seen: set[str] = set()
    for _slug, _git_root, project_root in projects:
        config = read_lens_toml(project_root)
        for repo in parse_dataset_repo_configs(config):
            if repo.name in seen:
                continue
            seen.add(repo.name)
            env_key = repo.name.upper().replace("-", "_")
            var_name = f"DATASET_REPO_DEPLOY_KEY_{env_key}"
            value = os.environ.get(var_name)
            if value:
                secrets[var_name] = value
    return secrets


def _collect_secrets(
    projects: list[tuple[str, Path, Path]],
    deploy_keys: dict[str, Path],
    username: str,
    password: str,
    remote_urls: dict[str, str],
) -> dict[str, str]:
    """Collect all secrets for a Fly deployment (single or multi-project).

    *projects* is [(slug, git_root, project_root), ...].
    *deploy_keys* maps slug → path to SSH deploy key.
    *remote_urls* maps slug → SSH remote URL.
    """
    secrets: dict[str, str] = {}

    hashed: str = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()  # type: ignore[no-untyped-call]
    secrets["CADDY_BASIC_AUTH_USER"] = username
    secrets["CADDY_BASIC_AUTH_HASH"] = hashed

    seen_api_key_env: set[str] = set()
    s3_needed = False

    for slug, _git_root, project_root in projects:
        env_key = _slug_to_env_key(slug)

        key_path = deploy_keys[slug]
        if not key_path.exists():
            raise LensException(f"project '{slug}': deploy key not found: {key_path}")
        secrets[f"GIT_REPO_DEPLOY_KEY_{env_key}"] = key_path.read_text()
        secrets[f"PROJECT_REPO_URL_{env_key}"] = remote_urls[slug]

        config = read_lens_toml(project_root)
        _append_project_api_key_secrets(config, secrets, seen_api_key_env)

        raw_project = config.get("project", {})
        proj: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}
        mount_point = proj.get("mount_point", "")
        if isinstance(mount_point, str) and mount_point.strip().startswith("s3://"):
            s3_needed = True

    if s3_needed:
        for var in _AWS_ENV_VARS:
            value = os.environ.get(var)
            if not value:
                raise LensException(
                    f"S3 mount configured but {var} is not set in your environment"
                )
            secrets[var] = value

    dataset_repo_secrets = collect_dataset_repo_deploy_key_secrets(projects)
    secrets.update(dataset_repo_secrets)

    return secrets


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        stderr = r.stderr.strip() or r.stdout.strip()
        raise LensException(f"{' '.join(args[:3])}… failed: {stderr}")
    return r


def _resolve_external_datasets(project_root: Path) -> list[tuple[str, Path]]:
    """Return ``[(name, path)]`` for datasets not bundled with Lens."""
    ds_root = datasets_root().resolve()
    external: list[tuple[str, Path]] = []
    for name in get_selected_datasets(project_root):
        path = resolve_dataset_path(project_root, name)
        if path is None:
            raise LensException(
                f"dataset '{name}' not found — cannot deploy. "
                f"Checked {datasets_root() / name} and {datasets_root().parent.parent / name}"
            )
        if not path.resolve().is_relative_to(ds_root):
            external.append((name, path))
    return external


def _fly_deploy(
    build_context: Path,
    fly_toml: Path,
    *,
    build_mode: FlyDeployBuildMode = FlyDeployBuildMode.fly,
) -> None:
    """Run ``fly deploy`` against a build context directory.

    *build_mode* selects ``fly deploy`` flags: Fly remote builder without Depot
    (``--depot=false``), Depot (``--depot=true``), or local Docker
    (``--local-only``).
    """
    dockerfile = build_context / "deploy" / "Dockerfile"
    lens_version = compute_local_version(repo_root=_LENS_ROOT)
    cmd: list[str] = [
        "fly",
        "deploy",
        "--build-arg",
        f"LENS_VERSION={lens_version}",
        str(build_context),
        "--config",
        str(fly_toml),
        "--dockerfile",
        str(dockerfile),
    ]
    match build_mode:
        case FlyDeployBuildMode.local:
            cmd.append("--local-only")
        case FlyDeployBuildMode.fly:
            cmd.append("--depot=false")
        case FlyDeployBuildMode.depot:
            cmd.append("--depot=true")
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise LensException("fly deploy failed")


def _validate_dependents_are_deployed(
    leader_slug: str, leader_raw: dict[str, Any], deployed_slugs: set[str],
) -> None:
    """Raise when the leader declares a dependent this deployment doesn't serve.

    A ``[[dependent_project]]`` entry only describes the topology for CI.
    The container derives the projects it actually serves from the
    ``PROJECT_REPO_URL_*`` Fly secrets, which are written by ``lens release
    add`` alongside ``fly.toml``'s ``LENS_PROJECT_SLUGS`` — so an entry added
    by hand deploys nothing at all, silently.
    """
    undeployed = sorted(
        dep.name for dep in parse_dependent_project_configs(leader_raw)
        if dep.name not in deployed_slugs
    )
    if not undeployed:
        return
    raise LensException(
        f"release leader '{leader_slug}' declares [[dependent_project]] entries "
        f"that this deployment does not serve: {', '.join(undeployed)}. The "
        "served projects come from the PROJECT_REPO_URL_* Fly secrets, which "
        "only 'lens release add' writes. Run 'lens release add <slug> "
        "--deploy-key <path>' — the slug must match the project's directory "
        "name — or remove the stale entry from the leader's lens.toml."
    )


def _validate_release_topology(projects: list[tuple[str, Path, Path]]) -> Path | None:
    """Cross-project ``[release]``/``[[dataset_repo]]`` consistency check.

    *projects* is ``[(slug, git_root, project_root), ...]``. Raises
    ``LensException`` via :func:`validate_deploy_topology` when more than
    one project claims ``app_leader`` (or none do while more than one has
    ``[release]`` enabled), or when sibling projects declare conflicting
    ``[[dataset_repo]]`` entries for the same name. Those checks are
    cross-project and so are skipped for a single project.

    Also raises via :func:`_validate_dependents_are_deployed` when a release
    project declares a ``[[dependent_project]]`` that is not among the
    deployed slugs — that one applies to single-project deployments too,
    since a leader with one served project may still declare dependents.

    Returns the release leader's project root when exactly one project sets
    ``[release] app_leader = true`` (``None`` for a single project, or a
    multi-project deployment with no designated leader).
    """
    deployed_slugs = {slug for slug, _git_root, _project_root in projects}
    project_configs: list[tuple[str, ReleaseConfig, list[DatasetRepoConfig]]] = []
    leader_root: Path | None = None
    for slug, _git_root, project_root in projects:
        raw = read_lens_toml(project_root)
        cfg = parse_release_config(raw)
        project_configs.append((slug, cfg, parse_dataset_repo_configs(raw)))
        if cfg.app_leader:
            leader_root = project_root
        if cfg.app_leader or cfg.enabled:
            _validate_dependents_are_deployed(slug, raw, deployed_slugs)
    if len(projects) <= 1:
        return None
    validate_deploy_topology(project_configs)
    return leader_root


def init_deploy(
    deploy_dir: Path,
    app_name: str,
    region: str,
    username: str,
    password: str,
    deploy_keys: dict[str, Path],
) -> Path:
    """Create Fly app, volume, set secrets, and generate fly.toml.

    Works for both single-project (one slug, ``deploy_dir`` is the project dir)
    and multi-project (multiple slugs, ``deploy_dir`` is the parent dir).
    *deploy_keys* maps slug → path to SSH deploy key.

    When a multi-project deployment designates a release leader
    (``[release] app_leader = true`` on exactly one of the given projects),
    ``fly.toml`` is written inside that leader's project directory instead
    of ``deploy_dir`` — the leader-colocated topology (see "Multi-project
    deployments" in ``deploy/README.md``), letting the leader's own git repo
    track and version the deployment config. Returns the path to the
    generated ``fly.toml``.
    """
    slugs = list(deploy_keys.keys())
    projects = build_projects(deploy_dir, slugs)
    leader_root = _validate_release_topology(projects)

    remote_urls: dict[str, str] = {}
    s3_buckets: list[str] = []
    for slug, git_root, project_root in projects:
        remote_url = _validate_project_for_deploy(slug, project_root, git_root)
        remote_urls[slug] = remote_url

        config = read_lens_toml(project_root)
        raw_project = config.get("project", {})
        proj: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}
        mount_point = proj.get("mount_point", "")
        if isinstance(mount_point, str) and mount_point.strip().startswith("s3://"):
            s3_buckets.append(_get_s3_bucket(mount_point.strip()))

    if len(set(s3_buckets)) > 1:
        raise LensException(
            f"all projects must use the same S3 bucket, "
            f"found: {', '.join(sorted(set(s3_buckets)))}"
        )

    secrets = _collect_secrets(projects, deploy_keys, username, password, remote_urls)

    fly_toml_dir = leader_root if leader_root is not None else deploy_dir
    fly_toml = fly_toml_dir / "fly.toml"
    fly_toml.write_text(
        _FLY_TOML_TEMPLATE.format(
            app_name=app_name,
            region=region,
            slugs=",".join(slugs),
        )
    )

    _run(["fly", "apps", "create", app_name, "--machines"])
    _run([
        "fly", "volumes", "create", "lens_data",
        "--region", region,
        "--size", "1",
        "--app", app_name,
        "--yes",
    ])
    secret_args = [f"{k}={v}" for k, v in secrets.items()]
    _run(["fly", "secrets", "set", "--app", app_name] + secret_args)
    return fly_toml



def add_project(deploy_dir: Path, slug: str, deploy_key_path: Path) -> None:
    """Add a project to an existing deployment.

    Updates ``fly.toml`` (adds slug to ``LENS_PROJECT_SLUGS``) and sets
    the per-project secrets on the Fly app.  Run ``lens deploy push``
    afterwards to apply.

    Raises :class:`LensException` if any project in the deployment has
    ``[release] enabled`` — use ``lens release add`` instead.
    """
    fly_toml = deploy_dir / "fly.toml"
    app_name = get_fly_app_name(fly_toml)
    current_slugs = get_slugs(fly_toml)

    if slug in current_slugs:
        raise LensException(f"project '{slug}' is already in this deployment")

    from lens.core.project import find_git_root_from

    project_root = resolve_project_root_for_slug(deploy_dir, slug)
    try:
        git_root = find_git_root_from(project_root)
    except RuntimeError as exc:
        raise LensException(f"project '{slug}': {exc}") from exc

    remote_url = _validate_project_for_deploy(slug, project_root, git_root)
    all_projects = build_projects(deploy_dir, current_slugs + [slug])
    _validate_release_topology(all_projects)

    env_key = _slug_to_env_key(slug)
    if not deploy_key_path.exists():
        raise LensException(f"deploy key not found: {deploy_key_path}")
    secrets: dict[str, str] = {
        f"GIT_REPO_DEPLOY_KEY_{env_key}": deploy_key_path.read_text(),
        f"PROJECT_REPO_URL_{env_key}": remote_url,
    }
    config = read_lens_toml(project_root)
    seen_keys: set[str] = set()
    _append_project_api_key_secrets(config, secrets, seen_keys)

    # Re-sync dataset repo deploy keys from all projects (existing + new)
    all_projects = build_projects(deploy_dir, current_slugs + [slug])
    dataset_repo_secrets = collect_dataset_repo_deploy_key_secrets(all_projects)
    secrets.update(dataset_repo_secrets)

    secret_args = [f"{k}={v}" for k, v in secrets.items()]
    _run(["fly", "secrets", "set", "--app", app_name] + secret_args)
    _update_slugs_in_fly_toml(fly_toml, current_slugs + [slug])


def remove_project(deploy_dir: Path, slug: str) -> None:
    """Remove a project from an existing deployment.

    Updates ``fly.toml`` (removes slug from ``LENS_PROJECT_SLUGS``) and
    unsets the per-project secrets on the Fly app.  Run ``lens deploy push``
    afterwards to apply.

    Raises :class:`LensException` if any project in the deployment has
    ``[release] enabled`` — use ``lens release remove`` instead.
    """
    fly_toml = deploy_dir / "fly.toml"
    app_name = get_fly_app_name(fly_toml)
    current_slugs = get_slugs(fly_toml)

    if slug not in current_slugs:
        raise LensException(f"project '{slug}' is not in this deployment")

    new_slugs = [s for s in current_slugs if s != slug]
    if not new_slugs:
        raise LensException(
            f"cannot remove '{slug}': it is the only project. "
            "Delete the Fly app instead, or add another project first."
        )

    _update_slugs_in_fly_toml(fly_toml, new_slugs)

    env_key = _slug_to_env_key(slug)
    _run([
        "fly", "secrets", "unset", "--app", app_name,
        f"GIT_REPO_DEPLOY_KEY_{env_key}",
        f"PROJECT_REPO_URL_{env_key}",
    ])


def push_deploy(
    deploy_dir: Path,
    *,
    build_mode: FlyDeployBuildMode = FlyDeployBuildMode.fly,
) -> None:
    """Deploy (or redeploy) the Lens application to Fly.io.

    *deploy_dir* is the directory containing ``fly.toml`` — the project
    directory itself (single-project, or the release leader in the
    leader-colocated multi-project topology) or a bare parent directory
    (multi-project).  External datasets from all projects are bundled into
    the Docker build context if needed.

    Refreshes Fly secrets for every ``api_key_env`` referenced in ``[[llm]]``,
    ``[[image]]``, and ``[[speech]]`` across all deployed projects (values read
    from the local environment), so new models/keys can be pushed without ``init``.

    *build_mode* controls how ``fly deploy`` builds the image; see
    :class:`FlyDeployBuildMode`.
    """
    fly_toml = deploy_dir / "fly.toml"
    slugs = get_slugs(fly_toml)  # also validates fly.toml exists
    app_name = get_fly_app_name(fly_toml)

    projects = build_projects(deploy_dir, slugs)
    _validate_release_topology(projects)
    api_key_secrets = collect_all_project_api_key_secrets(projects)
    if api_key_secrets:
        secret_args = [f"{k}={v}" for k, v in api_key_secrets.items()]
        _run(["fly", "secrets", "set", "--app", app_name] + secret_args)

    # Re-sync dataset repo deploy keys from all projects
    dataset_repo_secrets = collect_dataset_repo_deploy_key_secrets(projects)
    if dataset_repo_secrets:
        secret_args = [f"{k}={v}" for k, v in dataset_repo_secrets.items()]
        _run(["fly", "secrets", "set", "--app", app_name] + secret_args)

    seen_names: set[str] = set()
    all_external: list[tuple[str, Path]] = []
    for _slug, _git_root, project_root in projects:
        for name, path in _resolve_external_datasets(project_root):
            if name not in seen_names:
                seen_names.add(name)
                all_external.append((name, path))

    if not all_external:
        _fly_deploy(_LENS_ROOT, fly_toml, build_mode=build_mode)
        return

    with tempfile.TemporaryDirectory(prefix="lens-deploy-") as tmp:
        ctx = Path(tmp) / "context"
        _IGNORE = shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            ".dev-project",
            "node_modules",
            "__pycache__",
            ".DS_Store",
            "e2e",
            "bench",
            "docs",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "htmlcov",
        )
        shutil.copytree(_LENS_ROOT, ctx, ignore=_IGNORE, copy_function=os.link)
        for name, path in all_external:
            shutil.copytree(path, ctx / "datasets" / name, ignore=_IGNORE, copy_function=os.link)
        _fly_deploy(ctx, fly_toml, build_mode=build_mode)
