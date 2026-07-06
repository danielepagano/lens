"""lens deploy — manage Fly.io deployment for a Lens project."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_APP_NAME,
    ARG_REGION,
    ARG_USERNAME,
    ARG_PASSWORD,
    ARG_PROJECT_SLUG,
    ARG_DEPLOY_KEY,
    CMD_DEPLOY,
    HELP_OPTS,
    DEPLOY_MODE,
    DEPLOY_KEY_HELP,
)
from lens.core.commands.deploy import (
    FlyDeployBuildMode,
    add_project,
    init_deploy,
    push_deploy,
    remove_project,
    resolve_deploy_dir,
)
from lens.core.exceptions import LensException

app = typer.Typer(
    no_args_is_help=True,
    help=CMD_DEPLOY,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


def release_gate(ctx: typer.Context) -> None:
    """Block non-init deploy commands when the topology declares [release]."""
    if ctx.invoked_subcommand == "init":
        return
    try:
        deploy_dir = resolve_deploy_dir(Path.cwd())
    except (RuntimeError, LensException):
        return

    fly_toml = deploy_dir / "fly.toml"
    from lens.core.commands.deploy import read_lens_toml, build_projects, get_slugs
    from lens.core.release.config import parse_release_config

    slugs = get_slugs(fly_toml)
    projects = build_projects(deploy_dir, slugs)
    for slug, _git_root, project_root in projects:
        raw = read_lens_toml(project_root)
        cfg = parse_release_config(raw)
        if cfg.enabled:
            typer.echo(
                f"Project '{slug}' has [release] enabled — use 'lens release' commands instead",
                err=True,
            )
            raise typer.Exit(1)


release_gate = app.callback()(release_gate)


@app.command()
def init(
    app_name: str = typer.Option(..., "--app", help=ARG_APP_NAME),
    region: str = typer.Option(..., "--region", help=ARG_REGION),
    username: str = typer.Option(..., "--user", help=ARG_USERNAME),
    password: str = typer.Option(
        ..., "--password",
        prompt="Basic Auth password for Caddy (used to log into the deployed Lens UI)",
        hide_input=True,
        help=ARG_PASSWORD,
    ),
    deploy_key: list[str] = typer.Option(
        [],
        "--deploy-key",
        help=DEPLOY_KEY_HELP,
    ),
) -> None:
    """Create Fly app, volume, set secrets, and generate fly.toml.

    Run from a project directory (lens.toml present) for single-project mode,
    or from a parent directory for multi-project mode (use slug=path for each
    --deploy-key to select which projects to deploy). In multi-project mode,
    if exactly one selected project sets [release] app_leader = true,
    fly.toml is written inside that leader's own project directory instead
    of the parent directory, so it's tracked by the leader's git repo (see
    "Multi-project deployments" in deploy/README.md).
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
            fly_toml = init_deploy(
                deploy_dir=project_root,
                app_name=app_name,
                region=region,
                username=username,
                password=password,
                deploy_keys={slug: Path(raw_key).expanduser()},
            )
            typer.echo(f"Created Fly app '{app_name}' in region '{region}'.")
            typer.echo(f"Generated {fly_toml}")
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

            fly_toml = init_deploy(
                deploy_dir=cwd,
                app_name=app_name,
                region=region,
                username=username,
                password=password,
                deploy_keys=parsed_keys,
            )
            typer.echo(f"Created Fly app '{app_name}' in region '{region}'.")
            typer.echo(f"Generated {fly_toml}")

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
        help=DEPLOY_MODE,
    ),
) -> None:
    """Deploy (or redeploy) the Lens application image to Fly.io.

    Run from the directory containing fly.toml (the project directory for
    single-project mode or the leader-colocated multi-project mode), from
    an ancestor project directory, or from the grandparent directory of a
    leader-colocated multi-project deployment — fly.toml is located
    automatically in all three cases.
    """
    try:
        deploy_dir = resolve_deploy_dir(Path.cwd())
        push_deploy(deploy_dir, build_mode=mode)
    except RuntimeError as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy push: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def add(
    slug: str = typer.Argument(..., help=ARG_PROJECT_SLUG),
    deploy_key: Path = typer.Option(..., "--deploy-key", help=ARG_DEPLOY_KEY),
) -> None:
    """Add a project to an existing multi-project deployment.

    Run from the directory containing fly.toml (a bare parent directory, or
    the release leader's own project directory in the leader-colocated
    topology), or from the grandparent directory — fly.toml is located
    automatically. Updates fly.toml and sets the project's secrets on the
    Fly app.  Run 'lens deploy push' afterwards to apply.
    """
    try:
        add_project(
            deploy_dir=resolve_deploy_dir(Path.cwd()),
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
    slug: str = typer.Argument(..., help=ARG_PROJECT_SLUG),
) -> None:
    """Remove a project from an existing multi-project deployment.

    Run from the directory containing fly.toml (a bare parent directory, or
    the release leader's own project directory in the leader-colocated
    topology), or from the grandparent directory — fly.toml is located
    automatically.  Updates fly.toml and removes the project's secrets from
    the Fly app.  Run 'lens deploy push' afterwards to apply.
    """
    try:
        remove_project(deploy_dir=resolve_deploy_dir(Path.cwd()), slug=slug)
        typer.echo(f"Removed '{slug}' from the deployment.")
        typer.echo("Run 'lens deploy push' to apply.")
    except RuntimeError as e:
        typer.echo(f"lens deploy remove: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens deploy remove: {e}", err=True)
        raise typer.Exit(1)
