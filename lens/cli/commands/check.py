from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_CHECK, HELP_OPTS, OPT_SKIP_NETWORK
from lens.core.commands.check import run_project_check
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_CHECK,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def check(
    skip_network: bool = typer.Option(
        False,
        "--skip-network",
        help=OPT_SKIP_NETWORK,
    ),
) -> None:
    """Verify lens.toml, API keys, optional mount, and related paths for this project."""
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens check: {e}", err=True)
        raise typer.Exit(1)

    result = run_project_check(session.project_root, skip_network=skip_network)
    for line in result.lines:
        prefix = {"ok": "  ok", "warn": "warn", "error": " ERR"}[line.severity]
        typer.echo(f"{prefix}  [{line.topic}] {line.detail}")

    if not result.ok:
        typer.echo("lens check: failed (see errors above)", err=True)
        raise typer.Exit(1)
    typer.echo("lens check: all required checks passed")
