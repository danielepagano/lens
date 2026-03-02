from __future__ import annotations

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.knowledge import KnowledgeObject, validate_ids_exist
from lens.core.commands.kb import (
    kb_add,
    kb_edit,
    kb_template,
    kb_tag,
    kb_delete,
    kb_copy,
    kb_rename,
    kb_get,
    check_invalid_tags,
)
from lens.core.exceptions import LensException
from lens.core.project import find_project_root

app = typer.Typer(no_args_is_help=True, help="Manage knowledge objects (add, edit, get, tag, template, copy, rename, delete).")


@app.command(no_args_is_help=True)
def add(
    id: str = typer.Argument(..., help="Object ID (type.key)"),
    content: str | None = typer.Argument(None, help="Object content (omit to create empty or no-op)"),
    use_template: bool = typer.Option(False, "-t", "--use-template", help="Use template content"),
) -> None:
    """Upsert a single knowledge object."""
    try:
        kb_add(id, content, use_template)
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
def tag(
    id: str = typer.Argument(..., help="Object ID"),
    add: list[str] = typer.Option([], "-a", "--add", help="Tag(s) to add"),
    remove: list[str] = typer.Option([], "-r", "--remove", help="Tag(s) to remove"),
) -> None:
    """Manage tags for an object."""
    try:
        current, invalid = kb_tag(id, add, remove)
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
def copy(
    source_id: str = typer.Argument(..., help="Source object ID (type.key)"),
    target_id: str = typer.Argument(..., help="Target object ID (must be valid and unused)"),
) -> None:
    """Copy an object to a new ID. Target type may differ; directory is created if needed."""
    try:
        kb_copy(source_id, target_id)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def rename(
    old_id: str = typer.Argument(..., help="Current object ID"),
    new_id: str = typer.Argument(..., help="New object ID (must be valid and unused)"),
) -> None:
    """Rename an object to a new ID. New type may differ; directory is created if needed."""
    try:
        kb_rename(old_id, new_id)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def edit(
    id: str = typer.Argument(..., help="Object ID (type.key); creates if new"),
    instruction: str = typer.Argument(..., help="AI instructions for what to write/change"),
    context: str | None = typer.Option(None, "--context", "-c", help="Narrative address to crawl for context (not available in dataset mode)"),
    include_template: bool = typer.Option(False, "--include-template", "-t", help="Include type template in prompt"),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(None, "--llm", "-l", help="LLM ID to use"),
) -> None:
    """Edit or create a knowledge object using AI."""
    if not instruction or not instruction.strip():
        typer.echo("Error: INSTRUCTION is required (AI instructions for what to write/change)", err=True)
        typer.echo("Example: lens kb edit person.hero 'add a dark secret'", err=True)
        raise typer.Exit(1)
    try:
        project_root = find_project_root()
        validate_ids_exist(project_root, list(pin) + list(unpin))
    except (RuntimeError, LensException) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    try:
        def _print_token(chunk: str) -> None:
            print(chunk, end="", flush=True)
        kb_edit(
            id,
            instruction,
            context_address=context,
            pins=list(pin),
            unpins=list(unpin),
            include_template=include_template,
            llm_id=llm,
            on_token=_print_token,
        )
        print()
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def get(
    ids: list[str] = typer.Argument(
        ...,
        help="Object ID(s); append + for one-hop linked objects, or ++ for full linked traversal",
    ),
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
