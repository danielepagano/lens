from __future__ import annotations

import typer

from lens.core.knowledge import KnowledgeObject
from lens.core.commands.kb import (
    kb_store,
    kb_template,
    kb_tags,
    kb_delete,
    kb_get,
    check_invalid_tags,
)
from lens.core.exceptions import LensException

app = typer.Typer(no_args_is_help=True)


@app.command(no_args_is_help=True)
def store(
    id: str = typer.Argument(..., help="Object ID (type.key)"),
    content: str | None = typer.Argument(None, help="Object content (omit to create empty or no-op)"),
    use_template: bool = typer.Option(False, "-t", "--use-template", help="Use template content"),
) -> None:
    """Upsert a single knowledge object."""
    try:
        kb_store(id, content, use_template)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def template(
    type_name: str = typer.Argument(..., help="Object type"),
    content: str | None = typer.Argument(None, help="Template content (omit to print existing)"),
) -> None:
    """Manage _template.md for a type."""
    try:
        tpl = kb_template(type_name, content)
        if tpl is not None:
            typer.echo(tpl)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def tags(
    id: str = typer.Argument(..., help="Object ID"),
    add: list[str] = typer.Option([], "-a", "--add", help="Tag(s) to add"),
    remove: list[str] = typer.Option([], "-r", "--remove", help="Tag(s) to remove"),
) -> None:
    """Manage tags for an object."""
    try:
        current, invalid = kb_tags(id, add, remove)
        typer.echo(", ".join(current) if current else "")
        if invalid:
            typer.echo(
                f"Warning: invalid dot-tag(s) {', '.join(invalid)} reference non-existent object(s)",
                err=True,
            )
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def delete(
    id: str = typer.Argument(..., help="Object ID to delete"),
) -> None:
    """Delete an object (file, tags, references)."""
    try:
        kb_delete(id)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def get(
    ids: list[str] = typer.Argument(..., help="Object ID(s); append ! for linked objects"),
    include_comments: bool = typer.Option(True, "--include-comments", help="Keep markdown comments"),
) -> None:
    """Fetch and print knowledge objects."""
    try:
        ordered_ids, objects = kb_get(ids)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    def _print(obj: KnowledgeObject) -> None:
        typer.echo(obj.format(include_comments=include_comments))
        if obj.tags:
            try:
                invalid = check_invalid_tags(obj.tags)
                if invalid:
                    typer.echo(f"  (invalid dot-tag: {', '.join(invalid)} does not exist)")
            except LensException:
                pass

    for cid in ordered_ids:
        if cid in objects:
            _print(objects[cid])
    for cid, obj in objects.items():
        if cid not in ordered_ids:
            _print(obj)
