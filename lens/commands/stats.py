"""Count knowledge objects and narrative nodes."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.address import NarrativeAddress
from lens.project import get_active_narrative, require_lens_context
from lens.storage import Storage

app = typer.Typer(invoke_without_command=True)


@app.callback()
def stats() -> None:
    """Count knowledge objects and narrative nodes."""
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens stats: {e}", err=True)
        raise typer.Exit(1)

    root = project_root
    knowledge = root / "knowledge"
    kb_count = (
        sum(
            1
            for p in knowledge.rglob("*.md")
            if p.name != "_template.md"
        )
        if knowledge.exists()
        else 0
    )
    type_count = (
        sum(1 for d in knowledge.iterdir() if d.is_dir()) if knowledge.exists() else 0
    )

    narrative = root / "narrative"
    trees: list[tuple[str, int]] = []
    if narrative.exists():
        for d in sorted(narrative.iterdir()):
            if d.is_dir():
                node_count = sum(1 for _ in d.rglob("*.md"))
                trees.append((d.name, node_count))

    typer.echo("Knowledge Store")
    typer.echo(f"  Types: {type_count}")
    typer.echo(f"  Objects: {kb_count}")
    typer.echo("Narrative trees:")
    for name, count in trees:
        typer.echo(f"  {name} ({count} nodes)")

    active = get_active_narrative(root)
    if active is not None:
        cursor_addr: NarrativeAddress = active.find_cursor_address()
        typer.echo(f"Active narrative cursor:  {cursor_addr}")
    else:
        typer.echo("Active narrative cursor:  (no active narrative)")

    storage = Storage(git_root)
    has_pending = storage.has_pending()
    typer.echo(f"Open transaction:         {'yes' if has_pending else 'no'}")
    if has_pending:
        owner = storage.detect_pending_owner()
        if owner is not None:
            typer.echo(f"Transaction owner:        {owner}")
        else:
            typer.echo("Transaction owner:        (non-operator changes)")
