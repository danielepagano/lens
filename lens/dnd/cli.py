"""D&D CLI commands (registered via dataset extension)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from lens.core.knowledge import KnowledgeStore
from lens.core.project import require_lens_context
from lens.dnd.balance_encounter import compute_encounters
from lens.dnd.check_stat import check_stat_block

app = typer.Typer(no_args_is_help=True, help="D&D specific tools", add_completion=False)


@app.command("balance")
def balance_encounter(
    input_file: str | None = typer.Option(  # pyright: ignore[reportUnknownMemberType]
        None,
        "--input",
        "-i",
        help="Path to JSON file containing tool parameters. If omitted, reads from stdin.",
    ),
) -> None:
    """Generate encounter proposals from an optional list of candidates and a required list."""
    _git_root, project_root = require_lens_context(Path.cwd())

    try:
        if input_file:
            with open(input_file, encoding="utf-8") as f:
                data = json.load(f)
        else:
            if sys.stdin.isatty():
                typer.echo("Error: Please provide --input or pipe JSON to stdin.", err=True)
                raise typer.Exit(1)
            data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        typer.echo(f"Error parsing JSON: {e}", err=True)
        raise typer.Exit(1)

    required = data.get("required", [])
    optional = data.get("optional", [])
    difficulty = data.get("difficulty", "moderate")
    pcs = data.get("pcs", [])
    allies = data.get("allies", [])

    if not pcs:
        typer.echo("Error: 'pcs' array is required in JSON payload.", err=True)
        raise typer.Exit(1)

    kb = KnowledgeStore.for_project(project_root)
    result = compute_encounters(required, optional, difficulty, pcs, allies, kb)
    typer.echo(result)


@app.command("check-stat")
def check_stat(
    target: str | None = typer.Argument(  # pyright: ignore[reportUnknownMemberType]
        None,
        metavar="[ID|FILE]",
        help="A KB id (stat.goblin-boss), or a file holding the block. Reads stdin when omitted.",
    ),
) -> None:
    """Proofread a stat block's arithmetic and tags (no opinion on the design).

    Takes whichever is handier: a stored object, a file, or the block on stdin.
    """
    if target:
        _git_root, project_root = require_lens_context(Path.cwd())
        store = KnowledgeStore.for_project(project_root)
        obj = store.get_objects([target]).get(target) if "." in target else None
        if obj is not None:
            tags = store.get_tags(target)
            front = "---\nid: {}\ntags:\n{}---\n".format(
                obj.id, "".join(f"  - {t}\n" for t in tags)
            )
            block = front + obj.text
        else:
            path = Path(target)
            if not path.is_file():
                typer.echo(
                    f"Error: '{target}' is neither a KB object in this project nor a file. "
                    "Pass a stat id (e.g. stat.goblin-boss), a path to a file holding the "
                    "block, or pipe the block to stdin.",
                    err=True,
                )
                raise typer.Exit(1)
            block = path.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            typer.echo(
                "Error: pass a stat id or a file path, or pipe the block to stdin.", err=True
            )
            raise typer.Exit(1)
        block = sys.stdin.read()

    if not block.strip():
        typer.echo("Error: no stat block text given.", err=True)
        raise typer.Exit(1)
    typer.echo(check_stat_block(block))
