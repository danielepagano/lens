from __future__ import annotations

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.knowledge import KnowledgeObject, validate_ids_exist
from lens.core.commands.kb import (
    kb_add,
    kb_edit,
    kb_extract,
    kb_template,
    kb_tag,
    kb_delete,
    kb_copy,
    kb_rename,
    kb_get,
    kb_with_tag,
    check_invalid_tags,
)
from lens.core.exceptions import LensException
from lens.core.project import find_project_root
from pathlib import Path

app = typer.Typer(no_args_is_help=True, help="Manage knowledge objects (add, edit, get, tag, template, copy, rename, delete, with-tag, extract).")


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


@app.command("with-tag", no_args_is_help=True)
def with_tag(
    tags: list[str] = typer.Argument(..., help="Tag(s) to query; object must have all (AND)"),
    expand: bool = typer.Option(False, "-e", "--expand", help="Print full objects instead of IDs"),
    recurse: int | None = typer.Option(
        None,
        "-r",
        "--recurse",
        help="Recursively follow dot-tags and list children; N limits depth, 0 = full traversal",
    ),
    same_type_only: bool = typer.Option(
        False,
        "-s",
        "--same-type",
        help="Filter by object type when starting tag is a dot-tag",
    ),
) -> None:
    """List object IDs that have all given tags; optionally expand or recurse by dot-tags (map-style back-traversal)."""
    if not tags:
        typer.echo("Error: at least one tag is required", err=True)
        raise typer.Exit(1)
    try:
        result = kb_with_tag(
            tags,
            expand=expand,
            recurse=recurse,
            same_type_only=same_type_only,
        )
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    def _print_obj(obj: KnowledgeObject) -> None:
        typer.echo(obj.format(include_comments=True))
        if obj.tags:
            try:
                invalid = check_invalid_tags(obj.tags)
                if invalid:
                    typer.echo(f"  (invalid dot-tag: {', '.join(invalid)} does not exist)")
            except LensException:
                pass

    if recurse is None:
        if not expand:
            for cid in result.ids:
                typer.echo(cid)
        else:
            for cid in result.ids:
                if result.objects and cid in result.objects:
                    _print_obj(result.objects[cid])
    else:
        if not expand:
            if result.ids or result.layers:
                typer.echo(f"# Objects with tag {tags[0]!r}")
                for cid in result.ids:
                    typer.echo(cid)
            if result.layers:
                for parent_tag, child_ids in result.layers:
                    typer.echo(f"\n> with-tag {parent_tag!r}")
                    for cid in child_ids:
                        typer.echo(cid)
        else:
            for cid in result.ids:
                if result.objects and cid in result.objects:
                    _print_obj(result.objects[cid])
            if result.layers and result.objects:
                for parent_tag, child_ids in result.layers:
                    typer.echo(f"\n# From tag {parent_tag!r}")
                    for cid in child_ids:
                        if cid in result.objects:
                            _print_obj(result.objects[cid])


def _collect_markdown_files(root: Path) -> list[str]:
    """Return .md files under *root* in depth-first lexicographical order."""
    files: list[str] = []

    def _walk(dir_path: Path) -> None:
        entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
        for entry in entries:
            if entry.is_file() and entry.suffix == ".md":
                files.append(str(entry))
        for entry in entries:
            if entry.is_dir():
                _walk(entry)

    _walk(root)
    return files


@app.command(no_args_is_help=True)
def extract(
    path: str = typer.Argument(..., help="Markdown file or folder containing ```kb blocks"),
) -> None:
    """Extract and upsert KB objects from structured markdown (single transaction).

    Each ```kb block must contain YAML front matter (delimited by ---) with an
    'id' field and an optional 'tags' list. The block body becomes the object content.
    Content between blocks is ignored. When given a folder, all .md files within
    it (and its sub-folders) are processed in depth-first lexicographical order.
    """
    try:
        p = Path(path)
        if p.is_file():
            file_paths = [str(p)]
        elif p.is_dir():
            file_paths = _collect_markdown_files(p)
        else:
            raise LensException(f"file not found: {path}")

        result = kb_extract(file_paths)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    for err in result.errors:
        typer.echo(f"Warning: {err}", err=True)

    if result.inserted:
        typer.echo(f"Inserted: {', '.join(result.inserted)}")
    if result.updated:
        typer.echo(f"Updated: {', '.join(result.updated)}")
    if not result.inserted and not result.updated:
        typer.echo("No objects processed.")
    if result.errors and not result.inserted and not result.updated:
        raise typer.Exit(1)
