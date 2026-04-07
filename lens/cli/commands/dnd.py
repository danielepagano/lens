"""D&D specific tools and commands."""

import sys
import json
from pathlib import Path

import typer

from lens.core.knowledge import KnowledgeStore
from lens.core.project import require_lens_context
from lens.dnd.commands.balance_encounter import compute_encounters

app = typer.Typer(no_args_is_help=True, help="D&D specific tools", add_completion=False)
required_dataset = "lens-dnd"


@app.command("balance")
def balance_encounter(
    input_file: str = typer.Option(
        None,
        "--input",
        "-i",
        help="Path to JSON file containing tool parameters. If omitted, reads from stdin.",
    )
) -> None:
    """Generate encounter proposals from an optional list of candidates and a required list."""
    
    _git_root, project_root = require_lens_context(Path.cwd())
    
    try:
        if input_file:
            with open(input_file, "r") as f:
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
