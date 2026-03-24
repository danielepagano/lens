"""lens deploy — manage Fly.io deployment for a Lens project."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.core.commands.deploy import init_deploy, push_deploy
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
    deploy_key: Path = typer.Option(..., "--deploy-key", help="Path to SSH deploy key for project repo"),
) -> None:
    """Create Fly app, volume, set secrets, and generate fly.toml."""
    try:
        from lens.core.project import find_git_root, find_project_root

        project_root = find_project_root()
        git_root = find_git_root()
        init_deploy(
            project_root=project_root,
            git_root=git_root,
            app_name=app_name,
            region=region,
            username=username,
            password=password,
            deploy_key_path=deploy_key,
        )
        typer.echo(f"Created Fly app '{app_name}' in region '{region}'.")
        typer.echo(f"Generated {project_root / 'fly.toml'}")
        typer.echo("Next: lens deploy push")
    except RuntimeError as e:
        typer.echo(f"lens deploy init: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy init: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def push() -> None:
    """Deploy (or redeploy) the Lens application image to Fly.io."""
    try:
        from lens.core.project import find_project_root

        project_root = find_project_root()
        push_deploy(project_root)
    except RuntimeError as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)
