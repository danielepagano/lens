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


def build_projects(deploy_dir: Path, slugs: list[str]) -> list[tuple[str, Path, Path]]:
    """Return ``[(slug, git_root, project_root), ...]`` for the given slugs.

    When ``deploy_dir`` itself contains ``lens.toml`` (single-project: fly.toml
    lives inside the project directory), the project root is ``deploy_dir``
    regardless of the slug.  Otherwise (multi-project: fly.toml in a parent
    directory) each project root is ``deploy_dir / slug``.
    """
    from lens.core.project import find_git_root_from

    is_single = (deploy_dir / "lens.toml").exists()
    projects: list[tuple[str, Path, Path]] = []
    for slug in slugs:
        project_root = deploy_dir if is_single else deploy_dir / slug
        if not (project_root / "lens.toml").exists():
            raise LensException(f"project '{slug}': no lens.toml found at {project_root}")
        try:
            git_root = find_git_root_from(project_root)
        except RuntimeError as exc:
            raise LensException(f"project '{slug}': {exc}") from exc
        projects.append((slug, git_root, project_root))
    return projects


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


def _validate_release_topology(projects: list[tuple[str, Path, Path]]) -> None:
    """Cross-project ``[release]``/``[[dataset_repo]]`` consistency check.

    *projects* is ``[(slug, git_root, project_root), ...]``. No-op for a
    single project (nothing cross-project to reconcile). Raises
    ``LensException`` via :func:`validate_deploy_topology` when more than
    one project claims ``app_leader`` (or none do while more than one has
    ``[release]`` enabled), or when sibling projects declare conflicting
    ``[[dataset_repo]]`` entries for the same name.
    """
    if len(projects) <= 1:
        return
    project_configs: list[tuple[str, ReleaseConfig, list[DatasetRepoConfig]]] = []
    for slug, _git_root, project_root in projects:
        raw = read_lens_toml(project_root)
        project_configs.append(
            (slug, parse_release_config(raw), parse_dataset_repo_configs(raw))
        )
    validate_deploy_topology(project_configs)


def init_deploy(
    deploy_dir: Path,
    app_name: str,
    region: str,
    username: str,
    password: str,
    deploy_keys: dict[str, Path],
) -> None:
    """Create Fly app, volume, set secrets, and generate fly.toml.

    Works for both single-project (one slug, ``deploy_dir`` is the project dir)
    and multi-project (multiple slugs, ``deploy_dir`` is the parent dir).
    *deploy_keys* maps slug → path to SSH deploy key.
    """
    slugs = list(deploy_keys.keys())
    projects = build_projects(deploy_dir, slugs)
    _validate_release_topology(projects)

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

    fly_toml = deploy_dir / "fly.toml"
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


def add_project(deploy_dir: Path, slug: str, deploy_key_path: Path) -> None:
    """Add a project to an existing deployment.

    Updates ``fly.toml`` (adds slug to ``LENS_PROJECT_SLUGS``) and sets
    the per-project secrets on the Fly app.  Run ``lens deploy push``
    afterwards to apply.
    """
    fly_toml = deploy_dir / "fly.toml"
    app_name = get_fly_app_name(fly_toml)
    current_slugs = get_slugs(fly_toml)

    if slug in current_slugs:
        raise LensException(f"project '{slug}' is already in this deployment")

    from lens.core.project import find_git_root_from

    project_root = deploy_dir / slug
    if not (project_root / "lens.toml").exists():
        raise LensException(f"project '{slug}': no lens.toml found at {project_root}")
    try:
        git_root = find_git_root_from(project_root)
    except RuntimeError as exc:
        raise LensException(f"project '{slug}': {exc}") from exc

    remote_url = _validate_project_for_deploy(slug, project_root, git_root)
    _validate_release_topology(build_projects(deploy_dir, current_slugs + [slug]))

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

    *deploy_dir* is the directory containing ``fly.toml`` — either the
    project directory itself (single-project) or the parent directory
    (multi-project).  External datasets from all projects are bundled
    into the Docker build context if needed.

    Refreshes Fly secrets for every ``api_key_env`` referenced in ``[[llm]]``,
    ``[[image]]``, and ``[[speech]]`` across all deployed projects (values read
    from the local environment), so new models/keys can be pushed without ``init``.

    *build_mode* controls how ``fly deploy`` builds the image; see
    :class:`FlyDeployBuildMode`.
    """
    fly_toml = deploy_dir / "fly.toml"
    slugs = get_slugs(fly_toml)  # also validates fly.toml exists
    app_name = get_fly_app_name(fly_toml)
    is_single = (deploy_dir / "lens.toml").exists()

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
    for slug in slugs:
        project_root = deploy_dir if is_single else deploy_dir / slug
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
