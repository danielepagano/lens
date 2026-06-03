"""lens deploy — manage Fly.io deployment for a Lens project."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.core.commands.deploy import (
    FlyDeployBuildMode,
    add_project,
    init_deploy,
    push_deploy,
    remove_project,
)
from lens.core.exceptions import LensException

app = typer.Typer(
    no_args_is_help=True,
    help="Manage Fly.io deployment.",
    add_completion=False,
)


@app.command()
def init(
    app_name: str = typer.Option(..., "--app", help="Fly app name"),
    region: str = typer.Option(..., "--region", help="Fly region (e.g. lax, ams)"),
    username: str = typer.Option(..., "--user", help="Basic Auth username"),
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True, help="Basic Auth password"),
    deploy_key: list[str] = typer.Option(
        [],
        "--deploy-key",
        help=(
            "SSH deploy key. "
            "Single-project: path to key file (slug derived from directory name). "
            "Multi-project: slug=path, repeated for each project "
            "(e.g. --deploy-key proj-a=~/.ssh/key_a --deploy-key proj-b=~/.ssh/key_b). "
            "The slugs determine which projects are included."
        ),
    ),
) -> None:
    """Create Fly app, volume, set secrets, and generate fly.toml.

    Run from a project directory (lens.toml present) for single-project mode,
    or from a parent directory for multi-project mode (use slug=path for each
    --deploy-key to select which projects to deploy).
    """
    cwd = Path.cwd()
    is_single = (cwd / "lens.toml").exists()

    try:
        if is_single:
            # Single-project: --deploy-key is a plain path; slug = directory name
            if len(deploy_key) != 1:
                raise LensException(
                    "single-project mode requires exactly one --deploy-key <path>"
                )
            raw_key = deploy_key[0]
            if "=" in raw_key:
                raise LensException(
                    "single-project mode: --deploy-key should be a file path, not slug=path"
                )
            from lens.core.project import find_project_root

            project_root = find_project_root()
            slug = project_root.name
            init_deploy(
                deploy_dir=project_root,
                app_name=app_name,
                region=region,
                username=username,
                password=password,
                deploy_keys={slug: Path(raw_key).expanduser()},
            )
            typer.echo(f"Created Fly app '{app_name}' in region '{region}'.")
            typer.echo(f"Generated {project_root / 'fly.toml'}")
        else:
            # Multi-project: --deploy-key is slug=path, repeatable
            if not deploy_key:
                raise LensException(
                    "multi-project mode requires --deploy-key slug=path for each project to include"
                )
            parsed_keys: dict[str, Path] = {}
            for entry in deploy_key:
                if "=" not in entry:
                    raise LensException(
                        f"multi-project mode: --deploy-key must be slug=path, got: {entry!r}"
                    )
                slug, _, raw_path = entry.partition("=")
                slug = slug.strip()
                if not slug:
                    raise LensException(f"empty slug in --deploy-key: {entry!r}")
                parsed_keys[slug] = Path(raw_path.strip()).expanduser()

            init_deploy(
                deploy_dir=cwd,
                app_name=app_name,
                region=region,
                username=username,
                password=password,
                deploy_keys=parsed_keys,
            )
            typer.echo(f"Created Fly app '{app_name}' in region '{region}'.")
            typer.echo(f"Generated {cwd / 'fly.toml'}")

        typer.echo("Next: lens deploy push")
    except RuntimeError as e:
        typer.echo(f"lens deploy init: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy init: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def push(
    mode: FlyDeployBuildMode = typer.Option(
        FlyDeployBuildMode.fly,
        "--mode",
        help=(
            "fly: Fly remote builder without Depot (--depot=false). "
            "depot: Depot remote builder (--depot=true). "
            "local: build on this machine (--local-only)."
        ),
    ),
) -> None:
    """Deploy (or redeploy) the Lens application image to Fly.io.

    Run from the directory containing fly.toml (the project directory for
    single-project mode, or the parent directory for multi-project mode).
    """
    cwd = Path.cwd()
    try:
        if (cwd / "fly.toml").exists():
            deploy_dir = cwd
        else:
            # Walk up to find the project root (fly.toml should be there)
            from lens.core.project import find_project_root
            deploy_dir = find_project_root()
        push_deploy(deploy_dir, build_mode=mode)
    except RuntimeError as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def add(
    slug: str = typer.Argument(..., help="Project directory name (slug) to add"),
    deploy_key: Path = typer.Option(..., "--deploy-key", help="Path to SSH deploy key for the project repo"),
) -> None:
    """Add a project to an existing multi-project deployment.

    Run from the parent directory that contains fly.toml and the project
    subdirectory.  Updates fly.toml and sets the project's secrets on the
    Fly app.  Run 'lens deploy push' afterwards to apply.
    """
    try:
        add_project(
            deploy_dir=Path.cwd(),
            slug=slug,
            deploy_key_path=deploy_key.expanduser(),
        )
        typer.echo(f"Added '{slug}' to the deployment.")
        typer.echo("Run 'lens deploy push' to apply.")
    except RuntimeError as e:
        typer.echo(f"lens deploy add: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy add: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def remove(
    slug: str = typer.Argument(..., help="Project directory name (slug) to remove"),
) -> None:
    """Remove a project from an existing multi-project deployment.

    Run from the parent directory that contains fly.toml.  Updates fly.toml
    and removes the project's secrets from the Fly app.  Run 'lens deploy push'
    afterwards to apply.
    """
    try:
        remove_project(deploy_dir=Path.cwd(), slug=slug)
        typer.echo(f"Removed '{slug}' from the deployment.")
        typer.echo("Run 'lens deploy push' to apply.")
    except RuntimeError as e:
        typer.echo(f"lens deploy remove: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy remove: {e}", err=True)
        raise typer.Exit(1)
