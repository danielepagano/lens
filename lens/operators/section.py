"""Section operator: create and close child narrative nodes.

``lens section <id>`` creates a child node at the cursor and opens a
``[section:id]: #`` annotation in the parent.

``lens section --end`` closes the current section by appending a summary
placeholder and the closing annotation tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import typer

from lens.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.operator import Operator
from lens.project import get_active_narrative, require_lens_context, validate_slug
from lens.storage import Storage

SUMMARY_PLACEHOLDER = "> _(summary placeholder — replace with a summary of this section)_"


class SectionOperator(Operator):
    name: ClassVar[str] = "section"
    requires_id: ClassVar[bool] = True

    def start(self, id: str) -> None:
        """Create a child node and open the section annotation."""
        cursor = self.narrative_root.find_cursor()
        if id in cursor.child_keys():
            raise ValueError(f"section '{id}' already exists")
        self.create_subnode(cursor, id)

    def end(self) -> None:
        """Close the current section by appending summary + close tag."""
        cursor = self.narrative_root.find_cursor()
        if not cursor.key_path:
            raise ValueError("no open section to close (cursor at root)")
        parent_key_path = cursor.key_path[:-1]
        key = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=self.narrative_root.narrative_root,
            key_path=parent_key_path,
        )
        text = parent.md_path().read_text(encoding="utf-8")
        ann = find_unclosed_cursor_annotation(text)
        if ann is None or ann.operator != "section" or ann.id != key:
            raise ValueError(
                f"parent does not have unclosed [section:{key}]: #"
            )
        self.close_subnode(parent, key, SUMMARY_PLACEHOLDER)


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)


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
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    narrative = get_active_narrative(project_root)
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)

    if end:
        _section_end(git_root, narrative)
    else:
        if id_or_end is None:
            typer.echo("lens section: provide a section ID or use --end / -e", err=True)
            raise typer.Exit(1)
        _section_start(git_root, narrative, id_or_end.strip())


def _section_start(git_root: Path, narrative: NarrativeNode, id: str) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)
    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    cursor = narrative.find_cursor()
    cursor_md = cursor.md_path()
    rel = str(cursor_md.relative_to(git_root))
    owner = SectionOperator.owner_id(id, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        op.start(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _section_end(git_root: Path, narrative: NarrativeNode) -> None:
    cursor = narrative.find_cursor()
    if not cursor.key_path:
        typer.echo("lens section --end: no open section to close (cursor at root)", err=True)
        raise typer.Exit(1)
    key = cursor.key_path[-1]
    parent_key_path = cursor.key_path[:-1]
    parent = NarrativeNode(
        narrative_root=narrative.narrative_root,
        key_path=parent_key_path,
    )
    parent_md = parent.md_path()
    rel = str(parent_md.relative_to(git_root))
    owner = SectionOperator.owner_id(key, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        op.end()
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed section '{key}'")
