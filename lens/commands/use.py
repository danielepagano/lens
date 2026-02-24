"""Select narrative and create folder/_node.md if needed."""

from __future__ import annotations

import io
import tomllib
from typing import Any, cast

import tomli_w
import typer

from lens.project import find_git_root_from, find_project_root, validate_slug
from lens.storage import Storage

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)


@app.callback()
def use(
    slug: str = typer.Argument(..., help="Narrative slug (alphanumeric, underscores, hyphens)"),
) -> None:
    """Select narrative and create folder/_node.md if needed."""
    if not slug.strip():
        typer.echo("Error: SLUG cannot be empty.", err=True)
        raise typer.Exit(1)

    if not validate_slug(slug):
        typer.echo(
            f"Error: invalid slug '{slug}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        root = find_project_root()
        git_root = find_git_root_from(root)
    except RuntimeError as e:
        typer.echo(f"lens use: {e}", err=True)
        raise typer.Exit(1)

    storage = Storage(git_root)

    lens_toml = root / "lens.toml"
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_project = config.get("project", {})
    project: dict[str, Any] = (
        dict(cast(dict[str, Any], raw_project)) if isinstance(raw_project, dict) else {}
    )
    project["narrative"] = slug
    config["project"] = project

    buf = io.BytesIO()
    tomli_w.dump(config, buf)
    storage.write_file_bytes(lens_toml, buf.getvalue())

    narrative_dir = root / "narrative" / slug
    storage.mkdir(narrative_dir)

    node_path = narrative_dir / "_node.md"
    if not node_path.exists():
        storage.write_file(node_path, f"# {slug}\n")

    typer.echo(f"Using narrative '{slug}'")
