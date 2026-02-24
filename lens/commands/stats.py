"""Count knowledge objects and narrative nodes."""

from __future__ import annotations

import typer

from lens.project import find_project_root

app = typer.Typer(invoke_without_command=True)


@app.callback()
def stats() -> None:
    """Count knowledge objects and narrative nodes."""
    root = find_project_root()
    if root is None:
        typer.echo("lens stats: no lens.toml found (run 'lens init' first)", err=True)
        raise typer.Exit(1)

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
