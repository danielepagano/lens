"""lens release — CI-triggered release decision commands.

Two deployment systems exist:
  - ``lens deploy push`` — desktop build & deploy to Fly.io directly.
  - ``lens release`` — emit a CI contract so GitHub Actions / GitLab CI
    can deploy the Lens codebase itself.  This group inspects the project's
    ``[release]`` config, checks the upstream Lens repo for available
    versions, and drives the parent-hash gate for CI pipelines.

``lens release secrets check`` / ``sync`` manage the **CI-side** secret
inventory (different from desktop ``lens deploy push`` secrets — see
``deploy/README.md``)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_RELEASE_TAG,
    CMD_RELEASE,
    HELP_OPTS,
    OPT_JSON,
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
    help=(
        "Audit and sync secrets needed for CI release deployment.\n\n"
        "``check`` scans your project topology (leader, dependent projects,\n"
        "dataset repos) and lists every secret the CI pipeline needs:\n"
        "``api_key_env`` from ``[[llm]]``/``[[image]]``/``[[speech]]``,\n"
        "git deploy keys per project, and ``FLY_API_TOKEN`` (always required).\n\n"
        "Use this **before** setting up CI** to know exactly which repo-level\n"
        "secrets to create in your CI provider (GitHub Actions secrets,\n"
        "GitLab CI variables, etc.).  ``check`` also tells you whether each\n"
        "secret is already set on the Fly app (``--fly``), so you can skip\n"
        "redundant CI env vars for secrets Fly already has.\n\n"
        "``sync`` pushes whatever IS available in the CI env to Fly at deploy\n"
        "time — the CI counterpart of ``lens deploy push``'s secret step."
    ),
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)
app.add_typer(secrets_app, name="secrets")


@app.command(name="check")
def check() -> None:
    """Show the current release configuration and available versions.

    Displays which version is deployed, which is latest, and any
    pending deployment request.  The same information ``lens stats``
    and the web UI release modal show.

    Run from inside a project directory or a multi-project deploy
    directory (resolves to the release leader automatically).
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release check: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_check(project_root)
    except LensException as exc:
        typer.echo(f"lens release check: {exc}", err=True)
        raise typer.Exit(1)

    if not result.enabled:
        typer.echo("CI release not configured — add [release] enabled = true to lens.toml")
        return

    typer.echo("Release status:")
    typer.echo(f"  Lens repo:           {result.lens_repo_url}")
    if result.leader_repo_url:
        typer.echo(f"  Leader:              {result.leader_slug}  ({result.leader_repo_url})")
    else:
        typer.echo(f"  Leader:              {result.leader_slug}")
    typer.echo(f"  Installed version:   {result.installed_version or '(desktop checkout)'}")
    typer.echo(f"  Latest available:    {result.latest_available or '(unknown)'}")
    if result.update_available:
        typer.echo("  Update available:    Yes")
    if result.requested_version:
        typer.echo(f"  Requested version:   {result.requested_version}")
    if result.requested_from_commit:
        typer.echo(f"  Requested from:      {result.requested_from_commit[:12]}...")
    if result.remote_error:
        typer.echo(f"  Remote error:        {result.remote_error}")
    if result.dependent_projects:
        typer.echo("  Dependent projects:")
        for dep in result.dependent_projects:
            typer.echo(f"    - {dep['name']}  ({dep['git_url']}, ref: {dep['ref']})")
    if result.dataset_repos:
        typer.echo("  Dataset repos:")
        for ds in result.dataset_repos:
            typer.echo(f"    - {ds['name']}  ({ds['git_url']}, ref: {ds['ref']})")


@app.command(name="apply")
def apply(
    *,
    target: str | None = typer.Option(None, "--target", "-t", help=ARG_RELEASE_TAG),
) -> None:
    """Set the target version for deployment (UI Apply button equivalent).

    Without ``--target``, auto-resolves to the latest available tag on
    the upstream Lens repo.  With an explicit tag, validates and writes
    it to ``lens.toml``.  Symmetric with ``lens release clear``.

    Run from inside a project directory or a multi-project deploy
    directory (resolves to the release leader automatically).
    """
    try:
        project_root = resolve_release_project_root(Path.cwd())
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release apply: {exc}", err=True)
        raise typer.Exit(1)

    try:
        result = execute_release_apply(project_root, target)
    except LensException as exc:
        typer.echo(f"lens release apply: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(result.summary)


@app.command(name="clear")
def clear_cmd() -> None:
    """Cancel a pending release request (UI Clear button equivalent).

    Sets ``requested_version`` and ``requested_from_commit`` to empty
    strings in ``lens.toml`` (uncommitted).  Inverse of ``lens release apply``
    and the UI's Update action.
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

    typer.echo(result.summary)


@secrets_app.command(name="sync")
def secrets_sync(
    *,
    fly_app: str = typer.Option(..., "--fly-app", help="Fly app name to push secrets to"),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """Push whatever CI secrets are available to the Fly app (additive-only).

    Discovers topology (leader, ``[[dependent_project]]`` s,
    ``[[dataset_repo]]`` s), collects every secret whose env var is
    actually set in CI, and pushes them to Fly.  **Additive-only**:
    existing Fly secrets not present in the CI env are never touched.

    Only secrets that are actually set in the CI environment are pushed
    — see ``lens release secrets check`` for an audit of what's needed
    vs what's available.

    This is the CI counterpart of ``lens deploy push``'s secret step
    (which reads from your local shell instead).  Called by
    ``release.sh`` as part of the CI pipeline.
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
    if json_output:
        typer.echo(json.dumps(payload))
        if result.summary:
            typer.echo(result.summary, err=True)
    else:
        if result.summary:
            typer.echo(result.summary)


@secrets_app.command(name="check")
def secrets_check(
    *,
    check_fly: bool = typer.Option(False, "--fly", help="Check which secrets are already set on Fly app"),
    json_output: bool = typer.Option(False, "--json", help=OPT_JSON),
) -> None:
    """List every secret the CI pipeline needs and whether each is set.

    Scans your project topology (leader, ``[[dependent_project]]`` s,
    ``[[dataset_repo]]`` s, ``[[llm]]``/``[[image]]``/``[[speech]]``
    configs) and lists each secret with its source, whether it's
    available in the current CI environment (env var set), and optionally
    whether it's already on Fly (``--fly``).

    **Required in CI (always):** ``FLY_API_TOKEN`` — needed to authenticate
    ``flyctl deploy``.  Without this, the pipeline cannot deploy.

    **Required per project:** ``GIT_REPO_DEPLOY_KEY_<SLUG>`` for the leader
    and each ``[[dependent_project]]`` — SSH deploy keys that let the CI
    container clone private repos at boot time.

    **Required per API key:** the env var named in each ``api_key_env`` in
    ``[[llm]]``, ``[[image]]``, ``[[speech]]`` — if your project uses a
    remote model provider, its key must be available in CI.

    **Required per dataset repo:** ``DATASET_REPO_DEPLOY_KEY_<NAME>`` for
    each ``[[dataset_repo]]`` that needs private access.

    Use ``--fly`` to also check which of these already exist on the Fly
    app (from a previous deploy or manual ``fly secrets set``).  Secrets
    already present on Fly can be omitted from your CI env — only missing
    ones need adding.

    This is **not** the desktop deploy path — ``lens deploy push`` bundles
    secrets from your local shell automatically.  This check is for CI
    setup, where no interactive shell is available.
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

    need_in_ci: list[str] = []
    for s in result.secrets:
        env_sym = "✓" if s.set_in_env else "✗"
        name = s.name
        source = s.source
        fly_sym = "✓" if s.set_on_fly else "✗" if s.set_on_fly is False else "—"
        if not s.set_in_env:
            if not (s.set_on_fly is True and name != "FLY_API_TOKEN"):
                need_in_ci.append(name)
        typer.echo(f"  {name:<45} {source:<30} {env_sym:<5} {fly_sym:<5}")

    typer.echo()
    if need_in_ci:
        typer.echo("  Secrets to set in your CI provider:")
        for n in need_in_ci:
            if n == "FLY_API_TOKEN":
                typer.echo(f"    {n}  (always required — Fly auth)")
            else:
                typer.echo(f"    {n}")
    else:
        typer.echo("  All secrets present in environment — CI is ready.")

    if not check_fly:
        typer.echo()
        typer.echo("  Tip: pass --fly to check which secrets are already set on the Fly app.")
