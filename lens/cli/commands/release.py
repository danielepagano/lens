"""lens release — CI-friendly release decision commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from lens.cli.help_strings import (
    CMD_RELEASE,
    HELP_OPTS,
    OPT_JSON,
    ARG_RELEASE_TAG,
)
from lens.core.commands.release import (
    execute_release_apply,
    execute_release_check,
    resolve_release_project_root,
)
from lens.core.exceptions import LensException


app = typer.Typer(
    no_args_is_help=True,
    help=CMD_RELEASE,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


def _print_json(data: dict[str, str | None], summary: str, *, use_json: bool) -> None:
    if use_json:
        typer.echo(json.dumps(data))
        if summary:
            typer.echo(summary, err=True)
    else:
        if summary:
            typer.echo(summary)


_OPT_SINCE = "Commit SHA of the parent of the push range (e.g. `github.event.before`); checks every commit in `since..HEAD` for a parent match."


@app.command(name="check")
def check(
    *,
    since: str | None = typer.Option(None, "--since", help=_OPT_SINCE),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """Check for releases and emit the CI contract.

    Runs from inside a project directory, or from a multi-project deploy
    directory (parent of several projects sharing one ``fly.toml``) — in
    the latter case this resolves to whichever served project is the
    release leader (``[release] app_leader = true``).
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release check: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_check(project_root, since=since)
    except LensException as exc:
        typer.echo(f"lens release check: {exc}", err=True)
        raise typer.Exit(1)

    payload: dict[str, str | None] = {"action": result.action, "target": result.target}
    _print_json(payload, result.summary, use_json=json_output)


@app.command(name="apply")
def apply(
    *,
    to: str = typer.Option(..., "--to", help=ARG_RELEASE_TAG),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """Print build parameters for the requested tag.

    Runs from inside a project directory, or from a multi-project deploy
    directory — see ``lens release check``.
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release apply: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_apply(project_root, to)
    except LensException as exc:
        typer.echo(f"lens release apply: {exc}", err=True)
        raise typer.Exit(1)

    payload: dict[str, str | None] = {
        "lens_repo_url": result.lens_repo_url,
        "tag": result.tag,
    }
    _print_json(payload, result.summary, use_json=json_output)
