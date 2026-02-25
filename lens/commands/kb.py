"""Knowledge store CLI commands."""

from __future__ import annotations

import typer

from lens.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.project import find_project_root

app = typer.Typer(no_args_is_help=True)


def _get_store() -> KnowledgeStore:
    try:
        root = find_project_root()
    except RuntimeError as e:
        typer.echo(f"lens kb: {e}", err=True)
        raise typer.Exit(1)
    return KnowledgeStore(root)


@app.command(no_args_is_help=True)
def store(
    id: str = typer.Argument(..., help="Object ID (type.key)"),
    content: str | None = typer.Argument(None, help="Object content (omit to create empty or no-op)"),
    use_template: bool = typer.Option(False, "-t", "--use-template", help="Use template content"),
) -> None:
    """Upsert a single knowledge object."""
    kb = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    kb.store_object(id, content, use_template=use_template)


@app.command(no_args_is_help=True)
def template(
    type_name: str = typer.Argument(..., help="Object type"),
    content: str | None = typer.Argument(None, help="Template content (omit to print existing)"),
) -> None:
    """Manage _template.md for a type."""
    kb = _get_store()
    if content is not None:
        kb.set_template(type_name, content)
    else:
        tpl = kb.get_template(type_name)
        if tpl is not None:
            typer.echo(tpl)


@app.command(no_args_is_help=True)
def tags(
    id: str = typer.Argument(..., help="Object ID"),
    add: list[str] = typer.Option([], "-a", "--add", help="Tag(s) to add"),
    remove: list[str] = typer.Option([], "-r", "--remove", help="Tag(s) to remove"),
) -> None:
    """Manage tags for an object."""
    kb = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    if add:
        err = kb.add_tags(id, add)
        if err is not None:
            typer.echo(f"Error: {err}", err=True)
            raise typer.Exit(1)
    if remove:
        kb.remove_tags(id, remove)
    current = kb.get_tags(id)
    typer.echo(", ".join(current) if current else "")
    if current:
        invalid = kb.get_invalid_dot_tags(current)
        if invalid:
            typer.echo(
                f"Warning: invalid dot-tag(s) {', '.join(invalid)} reference non-existent object(s)",
                err=True,
            )


@app.command(no_args_is_help=True)
def delete(
    id: str = typer.Argument(..., help="Object ID to delete"),
) -> None:
    """Delete an object (file, tags, references)."""
    kb = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    kb.delete_object(id)


@app.command(no_args_is_help=True)
def get(
    ids: list[str] = typer.Argument(..., help="Object ID(s); append ! for linked objects"),
    include_comments: bool = typer.Option(True, "--include-comments", help="Keep markdown comments"),
) -> None:
    """Fetch and print knowledge objects."""
    kb = _get_store()
    ordered_ids, objects = kb.get_objects_with_links(ids)

    def _print(obj: KnowledgeObject) -> None:
        typer.echo(obj.format(include_comments=include_comments))
        if obj.tags:
            invalid = kb.get_invalid_dot_tags(obj.tags)
            if invalid:
                typer.echo(f"  (invalid dot-tag: {', '.join(invalid)} does not exist)")

    for cid in ordered_ids:
        if cid in objects:
            _print(objects[cid])
    for cid, obj in objects.items():
        if cid not in ordered_ids:
            _print(obj)
