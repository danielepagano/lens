from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_STATS, HELP_OPTS, OPT_VERBOSE
from lens.core.commands.stats import get_stats
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.release.status import compute_latest_available
from lens.core.release.version import compute_local_version, find_lens_repo_root

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_STATS,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def stats(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help=OPT_VERBOSE,
    ),
) -> None:
    """Count knowledge objects and narrative nodes."""
    try:
        session = ProjectSession.from_cwd()
        result = get_stats(session, verbose=verbose)
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens stats: {e}", err=True)
        raise typer.Exit(1)

    local_checkout_version: str | None = None
    if result.release_enabled and result.dataset_name is None and find_lens_repo_root() is not None:
        local_checkout_version = compute_local_version()

    latest_available: str | None = None
    if result.release_enabled and result.dataset_name is None and result.release_lens_repo_url:
        latest_available = compute_latest_available(session.project_root)

    if result.dataset_name is not None:
        typer.echo(f"Dataset: {result.dataset_name}")
    typer.echo("Knowledge Store")
    if result.kb_types:
        typer.echo(f"  Types: {','.join(sorted(result.kb_types))}")
    else:
        typer.echo("  Types: (none)")
    typer.echo(f"  Objects: {result.kb_count}")
    if result.dataset_name is None:
        if result.current_datasets:
            typer.echo(f"Current datasets: {','.join(result.current_datasets)}")
        else:
            typer.echo("Current datasets: (none)")

    if result.dataset_configs:
        for ds_name, cfg in result.dataset_configs.items():
            typer.echo(f"Dataset config ({ds_name}):")
            for key, value in cfg.items():
                typer.echo(f"  {key} = {value}")

    if result.available_llms:
        typer.echo(f"Available LLMs: {','.join(result.available_llms)}")
    else:
        typer.echo("Available LLMs: (none)")

    if result.image_backends:
        ids = ",".join(str(row["id"]) for row in result.image_backends)
        typer.echo(f"Available image backends: {ids}")
    else:
        typer.echo("Available image backends: (none)")

    if result.dataset_name is None:
        typer.echo("Narrative trees:")
        for name, count in result.trees:
            typer.echo(f"  {name} ({count} nodes)")

        if result.registered_modality_ids:
            typer.echo(
                "Registered modalities: "
                f"{','.join(result.registered_modality_ids)}"
            )
        else:
            typer.echo("Registered modalities: (none)")

        if result.cursor_addr is not None:
            typer.echo(f"Active narrative cursor: {result.cursor_addr}")
            if result.effective_pins_at_cursor:
                typer.echo(f"Effective pins at cursor: {','.join(result.effective_pins_at_cursor)}")
            else:
                typer.echo("Effective pins at cursor: (none)")
            if result.modalities_at_cursor:
                typer.echo("Modalities at cursor:")
                for modality_id in sorted(result.modalities_at_cursor):
                    info = result.modalities_at_cursor[modality_id]
                    status = "active" if info["active"] else "inactive"
                    line = f"  {modality_id}: {status}"
                    if info.get("config"):
                        line += f" (config: {info['config']})"
                    if info.get("reason"):
                        line += f" — {info['reason']}"
                    typer.echo(line)
            else:
                typer.echo("Modalities at cursor: (none)")
        else:
            typer.echo("Active narrative cursor:  (no active narrative)")

    if result.dataset_name is None and result.release_enabled:
        typer.echo("Release:")
        typer.echo(f"  Lens repo: {result.release_lens_repo_url}")
        if result.release_requested_version:
            typer.echo(f"  Requested version: {result.release_requested_version}")
        if result.release_requested_from_commit:
            typer.echo(f"  Requested from commit: {result.release_requested_from_commit}")
        if result.release_installed_version:
            typer.echo(f"  Installed: {result.release_installed_version}")
        elif local_checkout_version:
            typer.echo(f"  Local checkout: {local_checkout_version}")
        else:
            typer.echo("  Installed: (not deployed / LENS_VERSION unset)")
        if latest_available:
            typer.echo(f"  Latest available: {latest_available}")
        if result.release_app_leader:
            typer.echo("  App leader: yes (governs release for the whole Fly app)")
        if result.release_dataset_repos:
            for repo in result.release_dataset_repos:
                line = f"  Dataset repo: {repo['name']} -> {repo['git_url']} ({repo['ref']})"
                head_sha = repo.get("head_sha")
                if head_sha:
                    line = f"{line} @ {head_sha}"
                typer.echo(line)
    else:
        typer.echo("Release: not configured")

    typer.echo(f"Open transaction: {'yes' if result.has_pending else 'no'}")
    if result.has_pending:
        if result.pending_owner is not None:
            typer.echo(f"Transaction owner: {result.pending_owner}")
        else:
            typer.echo("Transaction owner: (non-operator changes)")

    if verbose:
        typer.echo("")
        typer.echo("=== Pending transaction (unstaged + untracked) ===")
        typer.echo(result.pending_diff if result.pending_diff else "(none)")
        typer.echo("=== Pending checkpoint (staged) ===")
        typer.echo(result.staged_diff if result.staged_diff else "(none)")
