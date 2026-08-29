"""Lens CLI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
import typer
from typer.core import TyperGroup

from lens.cli.commands import register_commands
from lens.cli.help_strings import APP, HELP_OPTS
from lens.cli.operators import register_operators
from lens.core.modalities.bootstrap import ensure_modalities_registered
from lens.core.project import (
    find_project_root_if_any,
    get_active_narrative,
    is_dataset_root,
    require_lens_context,
)

ensure_modalities_registered()

_DATASET_ALLOWED = frozenset({"stats", "kb", "prompt", "commit", "rollback", "serve", "dev", "check"})

#: Reading order for the panels in ``lens --help``: set the project up, do the
#: work, then the material the work reads.  Anything unlisted sorts to the end.
PANEL_ORDER: tuple[str, ...] = (
    "Project",
    "Operators",
    "Knowledge",
    "Media",
    "Dataset commands",
    "Serving & deploy",
)


class LensGroup(TyperGroup):
    """Top-level group that prints its help panels in a fixed reading order.

    Rich builds one panel per ``rich_help_panel`` in the order commands come out
    of :meth:`list_commands`, and Typer emits every plain command before every
    sub-group.  That makes panel order an accident of which modules happen to
    register a group, so it is decided here instead — alphabetically within each
    panel, which is the order a reader scans for a name they already half know.
    """

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = super().list_commands(ctx)

        def _rank(name: str) -> tuple[int, str]:
            command = self.get_command(ctx, name)
            panel = getattr(command, "rich_help_panel", None) or ""
            index = (
                PANEL_ORDER.index(panel) if panel in PANEL_ORDER else len(PANEL_ORDER)
            )
            return index, name

        return sorted(names, key=_rank)


app = typer.Typer(
    name="lens",
    cls=LensGroup,
    help=APP,
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(invoke_without_command=True)
def _preflight(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
    sub = ctx.invoked_subcommand
    if sub is None:
        return
    proj_root = find_project_root_if_any()
    if sub in ("init", "use") and proj_root is not None and is_dataset_root(proj_root):
        typer.echo(
            "lens: datasets don't use init/use; create lens.toml with [dataset] by hand",
            err=True,
        )
        raise typer.Exit(1)
    if sub == "skill":
        # Deliberately outside every gate below. The command's whole job is to
        # teach an agent that has just arrived, which is exactly when the
        # project may not be initialized, may be a dataset checkout, or may
        # have no active narrative — and a guide that refuses to print in those
        # cases is a guide nobody reads.
        return
    if sub in ("init", "use", "serve", "dev", "deploy", "release"):
        # `release` resolves its own project root (possibly a multi-project
        # deploy directory with no `lens.toml` of its own — see
        # `resolve_release_project_root`), so it must bypass the generic
        # git/narrative preflight below, same as `deploy`.
        return
    try:
        _git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens: {e}", err=True)
        raise typer.Exit(1)
    if is_dataset_root(project_root) and sub not in _DATASET_ALLOWED:
        typer.echo(f"lens: {sub} is not available in dataset mode", err=True)
        raise typer.Exit(1)
    if is_dataset_root(project_root):
        return
    _NO_NARRATIVE_NEEDED = (
        "kb",
        "prompt",
        "pin",
        "commit",
        "checkpoint",
        "refresh",
        "deploy",
        "check",
        "release",
    )
    if sub not in _NO_NARRATIVE_NEEDED:
        if get_active_narrative(project_root) is None:
            typer.echo("lens: no active narrative (run 'lens use <slug>' first)", err=True)
            raise typer.Exit(1)


register_commands(app)
register_operators(app)


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
