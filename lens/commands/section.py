"""Section operator: create and close child nodes."""

from __future__ import annotations

import typer

from lens.narrative import (
    NarrativeNode,
    find_cursor,
    find_unclosed_cursor_annotation,
    get_active_narrative,
    node_md_path,
    child_keys,
)
from lens.project import find_project_root, validate_slug

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)

SUMMARY_PLACEHOLDER = "> _(summary placeholder — replace with a summary of this section)_"


@app.callback()
def section(
    id_or_end: str | None = typer.Argument(
        None,
        help="Section ID to start (alphanumeric, underscores, hyphens)",
    ),
    end: bool = typer.Option(
        False,
        "--end",
        "-e",
        help="Close the current section",
    ),
) -> None:
    """Start a section at cursor or close the current section."""
    root = find_project_root()
    if root is None:
        typer.echo("lens section: no lens.toml found (run 'lens init' first)", err=True)
        raise typer.Exit(1)

    narrative = get_active_narrative(root)
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)

    if end:
        _section_end(narrative)
    else:
        if id_or_end is None:
            typer.echo("lens section: provide a section ID or use --end / -e", err=True)
            raise typer.Exit(1)
        _section_start(narrative, id_or_end.strip())


def _section_start(root: NarrativeNode, id: str) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)

    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    cursor = find_cursor(root)
    if id in child_keys(cursor):
        typer.echo(f"Error: section '{id}' already exists.", err=True)
        raise typer.Exit(1)

    md_path = node_md_path(cursor)
    if md_path is None:
        typer.echo("Error: cursor node has no content file.", err=True)
        raise typer.Exit(1)

    parent_dir = md_path.parent
    section_dir = parent_dir / id
    section_dir.mkdir(parents=True, exist_ok=True)
    node_md = section_dir / "_node.md"
    node_md.write_text(f"# {id}\n")

    content = md_path.read_text()
    sep = "\n" if content.endswith("\n") else "\n\n"
    suffix = sep + "[section:" + id + "]: #\n"
    md_path.write_text(content + suffix)

    typer.echo(f"Started section '{id}'")


def _section_end(root: NarrativeNode) -> None:
    cursor = find_cursor(root)
    if not cursor.key_path:
        typer.echo("lens section --end: no open section to close (cursor at root)", err=True)
        raise typer.Exit(1)

    parent_key_path = cursor.key_path[:-1]
    key = cursor.key_path[-1]
    parent = NarrativeNode(
        narrative_root=root.narrative_root,
        key_path=parent_key_path,
    )

    md_path = node_md_path(parent)
    if md_path is None:
        typer.echo("Error: parent node has no content file.", err=True)
        raise typer.Exit(1)

    text = md_path.read_text()
    ann = find_unclosed_cursor_annotation(text)
    if ann is None or ann.operator != "section" or ann.id != key:
        typer.echo(
            f"lens section --end: parent does not have unclosed [section:{key}]: #",
            err=True,
        )
        raise typer.Exit(1)

    sep = "\n" if text.endswith("\n") else "\n\n"
    suffix = sep + SUMMARY_PLACEHOLDER + "\n\n[/section:" + key + "]: #\n"
    md_path.write_text(text + suffix)

    typer.echo(f"Closed section '{key}'")
