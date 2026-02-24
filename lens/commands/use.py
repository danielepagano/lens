"""Select narrative and create folder/_node.md if needed."""

from __future__ import annotations

import tomllib
from typing import Any, cast

import tomli_w
import typer

from lens.project import find_project_root, validate_slug

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

    root = find_project_root()
    if root is None:
        typer.echo("lens use: no lens.toml found (run 'lens init' first)", err=True)
        raise typer.Exit(1)

    lens_toml = root / "lens.toml"
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_project = config.get("project", {})
    project: dict[str, Any] = (
        dict(cast(dict[str, Any], raw_project)) if isinstance(raw_project, dict) else {}
    )
    project["narrative"] = slug
    config["project"] = project

    with lens_toml.open("wb") as f:
        tomli_w.dump(config, f)

    narrative_dir = root / "narrative" / slug
    narrative_dir.mkdir(parents=True, exist_ok=True)

    node_path = narrative_dir / "_node.md"
    if not node_path.exists():
        node_path.write_text(f"# {slug}\n")

    typer.echo(f"Using narrative '{slug}'")
