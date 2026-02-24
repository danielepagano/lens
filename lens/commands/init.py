"""Initialize a Lens project in the current git repo."""

from __future__ import annotations


import tomli_w
import typer

from lens.project import find_git_root

app = typer.Typer(invoke_without_command=True)


@app.callback()
def init() -> None:
    """Initialize a Lens project in the current git repo."""
    root = find_git_root()
    if root is None:
        typer.echo("lens init: not in a git repository", err=True)
        raise typer.Exit(1)

    lens_toml = root / "lens.toml"
    if not lens_toml.exists():
        lens_toml.write_text("[project]\n# narrative selection set by 'lens use <slug>'\n")

    knowledge = root / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)

    tags_toml = knowledge / "tags.toml"
    if not tags_toml.exists():
        with tags_toml.open("wb") as f:
            tomli_w.dump({}, f)

    narrative = root / "narrative"
    narrative.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Initialized Lens project at {root}")
