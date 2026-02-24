"""Knowledge store CLI commands."""

from __future__ import annotations

import typer

from lens.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.project import find_project_root
from lens.annotations import strip_markdown_comments

app = typer.Typer(no_args_is_help=True)


def _get_store() -> KnowledgeStore:
    root = find_project_root()
    if root is None:
        typer.echo("lens kb: no lens.toml found (run 'lens init' first)", err=True)
        raise typer.Exit(1)
    return KnowledgeStore(root)


def _format_object(
    obj: KnowledgeObject,
    include_comments: bool,
    store: KnowledgeStore | None = None,
) -> str:
    text = obj.text if include_comments else strip_markdown_comments(obj.text)
    lines: list[str] = [f"KB[{obj.id!r}]"]
    indented = "  " + text.replace("\n", "\n  ")
    lines.append(indented)
    if obj.tags:
        lines.append(f"  TAGS={', '.join(obj.tags)}")
        if store is not None:
            invalid = store.get_invalid_dot_tags(obj.tags)
            if invalid:
                lines.append(f"  (invalid dot-tag: {', '.join(invalid)} does not exist)")
    return "\n".join(lines) + "\n"


@app.command(no_args_is_help=True)
def store(
    id: str = typer.Argument(..., help="Object ID (type.key)"),
    content: str | None = typer.Argument(None, help="Object content (omit to create empty or no-op)"),
    use_template: bool = typer.Option(False, "-t", "--use-template", help="Use template content"),
) -> None:
    """Upsert a single knowledge object."""
    store_impl = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    store_impl.store_object(id, content, use_template=use_template)


@app.command(no_args_is_help=True)
def template(
    type_name: str = typer.Argument(..., help="Object type"),
    content: str | None = typer.Argument(None, help="Template content (omit to print existing)"),
) -> None:
    """Manage _template.md for a type."""
    store_impl = _get_store()
    if content is not None:
        store_impl.set_template(type_name, content)
    else:
        tpl = store_impl.get_template(type_name)
        if tpl is not None:
            typer.echo(tpl)


@app.command(no_args_is_help=True)
def tags(
    id: str = typer.Argument(..., help="Object ID"),
    add: list[str] = typer.Option([], "-a", "--add", help="Tag(s) to add"),
    remove: list[str] = typer.Option([], "-r", "--remove", help="Tag(s) to remove"),
) -> None:
    """Manage tags for an object."""
    store_impl = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    if add:
        err = store_impl.add_tags(id, add)
        if err is not None:
            typer.echo(f"Error: {err}", err=True)
            raise typer.Exit(1)
    if remove:
        store_impl.remove_tags(id, remove)
    current = store_impl.get_tags(id)
    typer.echo(", ".join(current) if current else "")
    if current:
        invalid = store_impl.get_invalid_dot_tags(current)
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
    store_impl = _get_store()
    try:
        parse_id(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    store_impl.delete_object(id)


@app.command(no_args_is_help=True)
def get(
    ids: list[str] = typer.Argument(..., help="Object ID(s); append ! for linked objects"),
    include_comments: bool = typer.Option(False, "--include-comments", help="Keep markdown comments"),
) -> None:
    """Fetch and print knowledge objects."""
    store_impl = _get_store()
    requests: list[tuple[str, bool]] = []
    for raw in ids:
        if raw.endswith("!"):
            requests.append((raw[:-1], True))
        else:
            requests.append((raw, False))

    all_ids: list[str] = []
    seen: set[str] = set()
    get_linked_ids: set[str] = set()
    for cid, linked in requests:
        try:
            parse_id(cid)
        except ValueError:
            continue
        if cid not in seen:
            all_ids.append(cid)
            seen.add(cid)
        if linked:
            get_linked_ids.add(cid)

    if not all_ids:
        return

    objects = store_impl.get_objects(
        all_ids,
        expand_linked_for=get_linked_ids if get_linked_ids else None,
    )

    for cid in all_ids:
        if cid in objects:
            typer.echo(_format_object(objects[cid], include_comments, store_impl))
    for cid, obj in objects.items():
        if cid not in all_ids:
            typer.echo(_format_object(obj, include_comments, store_impl))
