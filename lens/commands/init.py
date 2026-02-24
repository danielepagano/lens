"""Initialize a Lens project in the current git repo."""

from __future__ import annotations

import io

import tomli_w
import typer

from lens.project import find_git_root
from lens.storage import Storage

app = typer.Typer(invoke_without_command=True)


@app.callback()
def init() -> None:
    """Initialize a Lens project in the current git repo."""
    try:
        root = find_git_root()
    except RuntimeError as e:
        typer.echo(f"lens init: {e}", err=True)
        raise typer.Exit(1)

    storage = Storage(root)

    lens_toml = root / "lens.toml"
    if not lens_toml.exists():
        storage.write_file(lens_toml, "[project]\n# narrative selection set by 'lens use <slug>'\n")

    storage.mkdir(root / "knowledge")

    tags_toml = root / "knowledge" / "tags.toml"
    if not tags_toml.exists():
        buf = io.BytesIO()
        tomli_w.dump({}, buf)
        storage.write_file_bytes(tags_toml, buf.getvalue())

    storage.mkdir(root / "narrative")

    typer.echo(f"Initialized Lens project at {root}")
