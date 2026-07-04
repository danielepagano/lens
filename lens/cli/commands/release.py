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
    execute_release_clear,
    execute_release_secrets_check,
    execute_release_secrets_sync,
    resolve_release_project_root,
)
from lens.core.exceptions import LensException


app = typer.Typer(
    no_args_is_help=True,
    help=CMD_RELEASE,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)

secrets_app = typer.Typer(
    no_args_is_help=True,
    help="Manage Fly secrets for release deployment",
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)
app.add_typer(secrets_app, name="secrets")


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


@app.command(name="clear")
def clear_cmd(
    *,
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """Clear a pending release request.

    Sets ``requested_version`` and ``requested_from_commit`` back to empty
    strings in ``lens.toml`` (uncommitted).  This is the inverse of the
    UI's *Update* action.
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release clear: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_clear(project_root)
    except LensException as exc:
        typer.echo(f"lens release clear: {exc}", err=True)
        raise typer.Exit(1)

    payload: dict[str, str | None] = {"status": "ok"}
    _print_json(payload, result.summary, use_json=json_output)


@secrets_app.command(name="sync")
def secrets_sync(
    *,
    fly_app: str = typer.Option(..., "--fly-app", help="Fly app name to push secrets to"),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """Synchronize CI-available secrets to the Fly app.

    Reads the project's ``lens.toml``, discovers ``[[dependent_project]]``
    topology, clones each dependent to read its API key config, collects all
    secrets that are set in the CI environment, and pushes them to Fly.

    Additive-only: existing Fly secrets not present in CI env are left
    untouched.
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release secrets sync: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_secrets_sync(project_root, fly_app)
    except LensException as exc:
        typer.echo(f"lens release secrets sync: {exc}", err=True)
        raise typer.Exit(1)

    payload: dict[str, str | None] = {
        "status": result.status,
        "secrets_set": str(result.secrets_set),
    }
    _print_json(payload, result.summary, use_json=json_output)


@secrets_app.command(name="check")
def secrets_check(
    *,
    check_fly: bool = typer.Option(False, "--fly", help="Check which secrets are already set on Fly app"),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """List every secret the release system needs and its status.

    Scans the project's ``lens.toml``, discovers ``[[dependent_project]]``
    topology, clones each dependent to read its API key config, then lists
    every environment variable the release pipeline needs.

    With ``--fly``, also checks which secrets are already set on the Fly app
    (requires ``fly.toml`` in the project root and ``fly`` CLI on PATH).
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release secrets check: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_secrets_check(project_root, check_fly=check_fly)
    except LensException as exc:
        typer.echo(f"lens release secrets check: {exc}", err=True)
        raise typer.Exit(1)

    if json_output:
        payload: dict[str, object] = {
            "leader_slug": result.leader_slug,
            "fly_app": result.fly_app,
            "project_slugs": result.project_slugs,
            "secrets": [
                {
                    "name": s.name,
                    "source": s.source,
                    "set_in_env": s.set_in_env,
                    "set_on_fly": s.set_on_fly,
                }
                for s in result.secrets
            ],
        }
        typer.echo(json.dumps(payload))
        return

    # Human-readable output
    typer.echo(f"Release secrets check for app: {result.fly_app or '(unknown)'}")
    typer.echo()
    typer.echo(f"  Leader:     {result.leader_slug}")
    if result.dependent_projects:
        dep_names = ", ".join(d.name for d in result.dependent_projects)
        typer.echo(f"  Dependents: {dep_names}")
    else:
        typer.echo("  Dependents: (none)")
    if result.dataset_repos:
        ds_names = ", ".join(r.name for r in result.dataset_repos)
        typer.echo(f"  Datasets:   {ds_names}")
    else:
        typer.echo("  Datasets:   (none)")

    typer.echo()
    typer.echo(f"  {'NAME':<45} {'SOURCE':<30} {'ENV':<5} {'FLY':<5}")
    typer.echo(f"  {'─'*44}  {'─'*28}  {'─'*3}  {'─'*3}")

    env_count = 0
    fly_ok = 0
    fly_total = 0
    for s in result.secrets:
        env_sym = "✓" if s.set_in_env else "✗"
        if s.set_in_env:
            env_count += 1
        fly_sym = "✓" if s.set_on_fly else "✗" if s.set_on_fly is False else "—"
        if s.set_on_fly is not None:
            fly_total += 1
            if s.set_on_fly:
                fly_ok += 1
        name = s.name
        source = s.source
        typer.echo(f"  {name:<45} {source:<30} {env_sym:<5} {fly_sym:<5}")

    typer.echo()
    typer.echo(
        f"  {env_count}/{len(result.secrets)} secrets set in environment",
    )
    if fly_total:
        typer.echo(f"  {fly_ok}/{fly_total} checkable secrets set on Fly")
    if not check_fly:
        typer.echo()
        typer.echo("  Tip: pass --fly to also check which secrets are set on the Fly app.")
