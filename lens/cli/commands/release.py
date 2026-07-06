"""lens release — release-managed deployments orchestrated by CI.

Once a project opts into `[release] enabled`, the CI-triggered workflow takes
over: `lens release check` emits the parent-hash gate, `lens release apply`
sets the target version, and `lens release secrets sync` keeps Fly secrets
in sync. `lens release init` installs the CI trigger files and (if no
`fly.toml` exists yet) bootstraps the Fly app with the same options as
`lens deploy init`. `lens release add` / `remove` manage the shared topology
(Fly secrets and `[[dependent_project]]`) and `lens release push` redeploys the
image from the release perspective. Use `lens deploy` commands for desktop-only
deployments that never opt into `[release] enabled`.

See [deploy/README.md](../../deploy/README.md) and
[docs/configuration.md](../../docs/configuration.md) for the full split
between desktop and release modes."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_APP_NAME,
    ARG_DEPLOY_KEY,
    ARG_PROJECT_SLUG,
    ARG_REGION,
    ARG_RELEASE_TAG,
    CMD_RELEASE,
    DEPLOY_KEY_HELP,
    DEPLOY_MODE,
    HELP_OPTS,
    OPT_JSON,
    OPT_RELEASE_INIT_AS_LEADER,
    OPT_RELEASE_INIT_LENS_REPO_URL,
    OPT_RELEASE_INIT_LEADER,
    RELEASE_INIT,
)
from lens.core.commands.release import (
    execute_release_apply,
    execute_release_check,
    execute_release_clear,
    execute_release_init,
    execute_release_secrets_check,
    execute_release_secrets_sync,
    release_add_project,
    release_push_deploy,
    release_remove_project,
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

    ci = result.ci_installation
    if ci.system:
        has_missing = len(ci.files_present) < len(ci.files_expected)
        is_problem = bool(ci.info) or has_missing or (ci.files_mismatched and ci.all_files_match is False)
        typer.echo(f"  CI installation:     {'PROBLEM' if is_problem else 'OK'}")
        typer.echo(f"    System:             {ci.system}")
        if ci.info and not ci.files_expected:
            typer.echo(f"    Config:             {ci.info}")
        for f in ci.files_expected:
            if f in ci.files_present:
                if f in ci.files_mismatched:
                    typer.echo(f"    Config:             {f}  (✗ - content differs)")
                else:
                    typer.echo(f"    Config:             {f}  (✓)")
            else:
                typer.echo(f"    Config:             {f}  (✗ — missing)")
        if ci.system in ("github", "gitlab"):
            if has_missing:
                typer.echo("    Fix:                Run 'lens release init' to install CI files")
            elif ci.files_mismatched:
                typer.echo("    Fix:                Run 'lens release init' to update CI files")

    if result.dependent_projects:
        typer.echo("  Dependent projects:")
        for dep in result.dependent_projects:
            typer.echo(f"    - {dep['name']}  ({dep['git_url']}, ref: {dep['ref']})")
    if result.dataset_repos:
        typer.echo("  Dataset repos:")
        for ds in result.dataset_repos:
            typer.echo(f"    - {ds['name']}  ({ds['git_url']}, ref: {ds['ref']})")

@app.command(name="init", help=RELEASE_INIT)
def init(
    *,
    lens_repo_url: str | None = typer.Option(
        None, "--lens-repo-url", "-u", help=OPT_RELEASE_INIT_LENS_REPO_URL,
    ),
    leader: bool = typer.Option(
        False, "--leader", "-l", help=OPT_RELEASE_INIT_LEADER,
    ),
    as_leader: str | None = typer.Option(
        None, "--as-leader", help=OPT_RELEASE_INIT_AS_LEADER,
    ),
    # Bootstrap options (when no fly.toml exists)
    app_name: str | None = typer.Option(
        None, "--app", help=ARG_APP_NAME,
    ),
    region: str | None = typer.Option(
        None, "--region", help=ARG_REGION,
    ),
    username: str | None = typer.Option(
        None, "--user", help="Basic Auth username for Caddy",
    ),
    password: str | None = typer.Option(
        None, "--password", help="Basic Auth password for Caddy",
    ),
    deploy_key: list[str] = typer.Option(
        [],
        "--deploy-key",
        help=DEPLOY_KEY_HELP,
    ),
) -> None:
    cwd = Path.cwd()
    effective_leader = leader or (as_leader is not None)

    # Standard resolution works from project dir or parent with existing leader
    try:
        project_root = resolve_release_project_root(cwd)
    except LensException as exc:
        if effective_leader and "no leader" in str(exc).lower():
            project_root = _resolve_project_from_deploy_dir(cwd, as_leader)
        else:
            typer.echo(f"lens release init: {exc}", err=True)
            raise typer.Exit(1)

    # Parse deploy_keys if provided
    fly_toml = project_root / "fly.toml"
    if not fly_toml.exists():
        fly_toml = (project_root.parent / "fly.toml")
    has_fly_toml = fly_toml.exists()
    bootstrap = not has_fly_toml

    parsed_keys: dict[str, Path] | None = None
    if bootstrap:
        missing: list[str] = []
        if not app_name:
            missing.append("--app")
        if not region:
            missing.append("--region")
        if not deploy_key:
            missing.append("--deploy-key")
        if missing:
            typer.echo(
                "This project has no fly.toml yet. Run `lens deploy init --app <name> --region <region> "
                "--user <user> --password <pw> --deploy-key <slug=path>` first, or rerun `lens release init` "
                f"with the missing flags ({', '.join(missing)}).",
                err=True,
            )
            raise typer.Exit(1)
        if not username:
            username = typer.prompt("Basic Auth username for Caddy")
        if not password:
            password = typer.prompt("Basic Auth password for Caddy", hide_input=True)
        parsed_keys = _parse_deploy_keys(cwd, project_root, deploy_key)

    try:
        result = execute_release_init(
            project_root,
            lens_repo_url=lens_repo_url,
            leader=effective_leader,
            app_name=app_name if bootstrap else None,
            region=region if bootstrap else None,
            username=username if bootstrap else None,
            password=password if bootstrap else None,
            deploy_keys=parsed_keys,
        )
    except LensException as exc:
        typer.echo(f"lens release init: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(result.summary)


def _resolve_project_from_deploy_dir(cwd: Path, as_leader: str | None) -> Path:
    """Pick a project from a parent deploy directory when no leader exists yet."""
    from lens.core.commands.deploy import (
        build_projects,
        find_colocated_fly_toml,
        get_slugs,
    )

    fly_toml = cwd / "fly.toml"
    if not fly_toml.exists():
        fly_toml = find_colocated_fly_toml(cwd)
    if fly_toml is None:
        raise LensException(
            "no fly.toml found — run 'lens deploy init' first or run "
            "'lens release init' from a project directory"
        )

    slugs = get_slugs(fly_toml)
    if not slugs:
        raise LensException(
            f"{fly_toml} has no project slugs — run 'lens deploy init' first"
        )

    if as_leader:
        if as_leader not in slugs:
            raise LensException(
                f"slug {as_leader!r} is not in {fly_toml} (slugs: {', '.join(slugs)})"
            )
        target_slug = as_leader
    elif len(slugs) == 1:
        target_slug = slugs[0]
    else:
        raise LensException(
            f"multiple projects in {fly_toml}: {', '.join(slugs)}. "
            "Run from the project directory directly, or pass "
            "--as-leader <slug> to specify which becomes the release leader."
        )

    projects = build_projects(fly_toml.parent, [target_slug])
    if not projects:
        raise LensException(f"could not resolve project {target_slug!r} from {fly_toml}")
    _slug, _git_root, proj_root = projects[0]
    return proj_root


def _parse_deploy_keys(cwd: Path, project_root: Path, deploy_key: list[str]) -> dict[str, Path]:
    """Parse --deploy-key arguments into slug → path mapping.

    Supports both single-project (plain path → slug from project_root.name)
    and multi-project (slug=path) formats.
    """
    is_single = (project_root / "lens.toml").exists() and (cwd == project_root or cwd == project_root.parent)
    if is_single:
        if len(deploy_key) != 1:
            raise LensException("single-project mode requires exactly one --deploy-key <path>")
        raw = deploy_key[0]
        if "=" in raw:
            raise LensException("single-project mode: --deploy-key should be a file path, not slug=path")
        return {project_root.name: Path(raw).expanduser()}
    parsed: dict[str, Path] = {}
    for entry in deploy_key:
        if "=" not in entry:
            raise LensException(
                "multi-project mode: --deploy-key must be slug=path, got: {entry!r}"
            )
        slug, _, raw_path = entry.partition("=")
        slug = slug.strip()
        if not slug:
            raise LensException(f"empty slug in --deploy-key: {entry!r}")
        parsed[slug] = Path(raw_path.strip()).expanduser()
    return parsed


@app.command(name="push")
def push(
    mode: str = typer.Option(
        "fly",
        "--mode",
        help=DEPLOY_MODE,
    ),
) -> None:
    """Deploy (or redeploy) the Lens application image to Fly.io.

    Identical to ``lens deploy push``.  Run from the directory containing
    ``fly.toml`` or from an ancestor project directory (``fly.toml`` is
    located automatically).
    """
    from lens.core.commands.deploy import resolve_deploy_dir

    try:
        deploy_dir = resolve_deploy_dir(Path.cwd())
        release_push_deploy(deploy_dir, build_mode=mode)
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release push: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="add")
def add(
    slug: str = typer.Argument(..., help=ARG_PROJECT_SLUG),
    deploy_key: Path = typer.Option(..., "--deploy-key", help=ARG_DEPLOY_KEY),
) -> None:
    """Add a project to an existing release-managed deployment.

    Sets Fly secrets, updates ``fly.toml``, and adds a
    ``[[dependent_project]]`` entry to the release leader's ``lens.toml``
    so CI discovers the new project.  Run ``lens release push`` afterwards
    to apply.
    """
    from lens.core.commands.deploy import resolve_deploy_dir

    try:
        deploy_dir = resolve_deploy_dir(Path.cwd())
        release_add_project(
            deploy_dir, slug=slug, deploy_key_path=deploy_key.expanduser(),
        )
        typer.echo(f"Added '{slug}' to the deployment.")
        typer.echo("Run 'lens release push' to apply.")
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release add: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="remove")
def remove(
    slug: str = typer.Argument(..., help=ARG_PROJECT_SLUG),
) -> None:
    """Remove a project from an existing release-managed deployment.

    Removes the ``[[dependent_project]]`` entry from the release leader's
    ``lens.toml``, unsets Fly secrets, and updates ``fly.toml``.
    Run ``lens release push`` afterwards to apply.
    """
    from lens.core.commands.deploy import resolve_deploy_dir

    try:
        deploy_dir = resolve_deploy_dir(Path.cwd())
        release_remove_project(deploy_dir, slug=slug)
        typer.echo(f"Removed '{slug}' from the deployment.")
        typer.echo("Run 'lens release push' to apply.")
    except (RuntimeError, LensException) as exc:
        typer.echo(f"lens release remove: {exc}", err=True)
        raise typer.Exit(1)


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
    deploy_missing: list[str] = []
    for s in result.secrets:
        env_sym = "✓" if s.set_in_env else "✗"
        name = s.name
        source = s.source
        fly_sym = "✓" if s.set_on_fly else "✗" if s.set_on_fly is False else "—"
        if name in ("CADDY_BASIC_AUTH_USER", "CADDY_BASIC_AUTH_HASH"):
            if s.set_on_fly is False:
                deploy_missing.append(name)
        else:
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

    if deploy_missing:
        typer.echo("")
        typer.echo("  Deployment secrets missing from Fly app:")
        for n in deploy_missing:
            typer.echo(f"    {n}")

        typer.echo("  Run 'lens deploy init' to configure the deployment (it sets these).")
    if not need_in_ci and not deploy_missing:
        typer.echo("  All secrets present — deployment is ready.")

    if not check_fly:
        typer.echo()
        typer.echo("  Tip: pass --fly to check which secrets are already set on the Fly app.")
