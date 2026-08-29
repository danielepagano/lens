from __future__ import annotations

import typer

from lens.cli.command_inventory import collect_command_inventory
from lens.cli.help_strings import (
    CMD_SKILL,
    HELP_OPTS,
    OPT_SKILL_CHECK,
    OPT_SKILL_INSTALL,
    OPT_SKILL_SOURCES,
)
from lens.core.commands.skill import (
    check_skill,
    collect_layers,
    install_skill,
    render_guidance,
)
from lens.core.exceptions import LensException
from lens.core.project import find_project_root_if_any, ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_SKILL,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def skill(
    install: bool = typer.Option(False, "--install", help=OPT_SKILL_INSTALL),
    check: bool = typer.Option(False, "--check", help=OPT_SKILL_CHECK),
    sources: bool = typer.Option(False, "--sources", help=OPT_SKILL_SOURCES),
) -> None:
    """Print what an agent needs to know about this project, generated now."""
    if install and check:
        typer.echo("lens skill: use either --install or --check, not both", err=True)
        raise typer.Exit(1)

    project_root = find_project_root_if_any()

    if install or check:
        if project_root is None:
            typer.echo(
                "lens skill: --install and --check need a Lens project "
                "(run 'lens init' first)",
                err=True,
            )
            raise typer.Exit(1)
        if check:
            result = check_skill(project_root)
            typer.echo(f"lens skill: {result.message()}")
            raise typer.Exit(0 if result.ok else 1)
        try:
            session = ProjectSession.from_cwd()
            path = install_skill(project_root, git_root=session.git_root)
        except (LensException, RuntimeError) as e:
            typer.echo(f"lens skill: {e}", err=True)
            raise typer.Exit(1)
        typer.echo(f"Installed agent skill at {path}")
        return

    commands = collect_command_inventory()

    if sources:
        for layer in collect_layers(project_root, commands):
            where = str(layer.path) if layer.path is not None else "(generated)"
            typer.echo(f"{layer.source}\t{where}")
        return

    if project_root is None:
        typer.echo(
            "lens skill: not inside a Lens project — printing the general guidance only",
            err=True,
        )
    typer.echo(render_guidance(project_root, commands), nl=False)
