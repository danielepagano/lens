"""Core logic for Fly.io deployment management."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, cast

import bcrypt  # type: ignore[import-untyped]

from lens.core.exceptions import LensException
from lens.core.project import datasets_root, get_selected_datasets, resolve_dataset_path
from lens.core.storage import Storage

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_FLY_TOML_TEMPLATE = """\
app = "{app_name}"
primary_region = "{region}"

[env]
  LENS_PROJECT_DIR = "/data/repo"
  LENS_PORT = "8000"
  CADDY_PORT = "8080"
  PROJECT_REPO_URL = "{remote_url}"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "suspend"
  auto_start_machines = true
  min_machines_running = 0

[[mounts]]
  source = "lens_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
"""

_AWS_ENV_VARS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "AWS_DEFAULT_REGION",
]


def _read_lens_toml(project_root: Path) -> dict[str, Any]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise LensException(f"{lens_toml} not found")
    with lens_toml.open("rb") as f:
        return tomllib.load(f)


def _collect_required_secrets(
    project_root: Path,
    username: str,
    password: str,
    deploy_key_path: Path,
) -> dict[str, str]:
    """Collect all secrets needed for Fly deployment."""
    config = _read_lens_toml(project_root)
    secrets: dict[str, str] = {}

    # Caddy auth — hash password for Caddy bcrypt format
    hashed: str = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()  # type: ignore[no-untyped-call]
    secrets["CADDY_BASIC_AUTH_USER"] = username
    secrets["CADDY_BASIC_AUTH_HASH"] = hashed

    # Deploy key
    if not deploy_key_path.exists():
        raise LensException(f"deploy key not found: {deploy_key_path}")
    secrets["GITLAB_DEPLOY_KEY"] = deploy_key_path.read_text()

    # LLM API keys from lens.toml [[llm]] entries
    raw_llm_list = config.get("llm", [])
    llm_list: list[Any] = cast(list[Any], raw_llm_list) if isinstance(raw_llm_list, list) else []
    seen_env_vars: set[str] = set()
    for raw_entry in llm_list:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        env_name = entry.get("api_key_env")
        if isinstance(env_name, str) and env_name not in seen_env_vars:
            seen_env_vars.add(env_name)
            value = os.environ.get(env_name)
            if not value:
                raise LensException(
                    f"lens.toml requires {env_name} but it is not set in your environment"
                )
            secrets[env_name] = value

    # S3 credentials if mount_point is an S3 URI
    raw_project = config.get("project", {})
    project: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}
    mount_point = project.get("mount_point", "")
    if isinstance(mount_point, str) and mount_point.startswith("s3://"):
        for var in _AWS_ENV_VARS:
            value = os.environ.get(var)
            if not value:
                raise LensException(
                    f"S3 mount configured but {var} is not set in your environment"
                )
            secrets[var] = value

    return secrets


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        stderr = r.stderr.strip() or r.stdout.strip()
        raise LensException(f"{' '.join(args[:3])}… failed: {stderr}")
    return r


def _resolve_external_datasets(project_root: Path) -> list[tuple[str, Path]]:
    """Return ``[(name, path)]`` for datasets not bundled with Lens.

    Resolves every dataset declared in lens.toml and filters to those
    whose resolved path is outside the bundled ``datasets/`` directory.
    Raises :class:`LensException` if any dataset cannot be found.
    """
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


def init_deploy(
    project_root: Path,
    git_root: Path,
    app_name: str,
    region: str,
    username: str,
    password: str,
    deploy_key_path: Path,
) -> None:
    """Create Fly app, volume, set secrets, and generate fly.toml in the project dir."""
    storage = Storage(git_root)

    # Get remote URL
    remote_url = storage.get_remote_url()

    # Collect all secrets
    secrets = _collect_required_secrets(project_root, username, password, deploy_key_path)

    # Generate fly.toml
    fly_toml = project_root / "fly.toml"
    fly_toml.write_text(
        _FLY_TOML_TEMPLATE.format(
            app_name=app_name,
            region=region,
            remote_url=remote_url,
        )
    )

    # Create Fly app
    _run(["fly", "apps", "create", app_name, "--machines"])

    # Create volume
    _run([
        "fly", "volumes", "create", "lens_data",
        "--region", region,
        "--size", "1",
        "--app", app_name,
        "--yes",
    ])

    # Set secrets
    secret_args = [f"{k}={v}" for k, v in secrets.items()]
    _run(["fly", "secrets", "set", "--app", app_name] + secret_args)


def _fly_deploy(build_context: Path, fly_toml: Path) -> None:
    """Run ``fly deploy`` against a build context directory."""
    dockerfile = build_context / "deploy" / "Dockerfile"
    result = subprocess.run(
        [
            "fly", "deploy", str(build_context),
            "--config", str(fly_toml),
            "--dockerfile", str(dockerfile),
        ],
        text=True,
    )
    if result.returncode != 0:
        raise LensException("fly deploy failed")


def push_deploy(project_root: Path) -> None:
    """Deploy (or redeploy) the Lens application to Fly.io.

    If the project uses external datasets (resolved outside the bundled
    ``datasets/`` directory), a temporary build context is created that
    copies them into ``datasets/`` so the Docker image contains everything.
    """
    fly_toml = project_root / "fly.toml"
    if not fly_toml.exists():
        raise LensException("fly.toml not found — run 'lens deploy init' first")

    external = _resolve_external_datasets(project_root)

    if not external:
        _fly_deploy(_LENS_ROOT, fly_toml)
        return

    # Build a temporary context with external datasets placed alongside bundled ones.
    # Uses hard links where possible (fast, no extra disk) with copy fallback.
    with tempfile.TemporaryDirectory(prefix="lens-deploy-") as tmp:
        ctx = Path(tmp) / "context"
        _IGNORE = shutil.ignore_patterns(".git", ".venv", "node_modules", "__pycache__", ".DS_Store")
        shutil.copytree(_LENS_ROOT, ctx, ignore=_IGNORE, copy_function=os.link)
        for name, path in external:
            shutil.copytree(path, ctx / "datasets" / name, ignore=_IGNORE, copy_function=os.link)
        _fly_deploy(ctx, fly_toml)
