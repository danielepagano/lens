from __future__ import annotations

import typer
from pathlib import Path

from lens.cli.async_cancel import run_with_cancel
from lens.cli.help_strings import (
    ARG_ID,
    ARG_INSTRUCTION,
    ARG_CONTENT_OPT,
    ARG_TYPE_NAME,
    ARG_SOURCE_ID,
    ARG_TARGET_ID,
    ARG_OLD_ID,
    ARG_NEW_ID,
    ARG_TYPE_FILTER,
    ARG_TAG_PREFIX,
    ARG_TAGS,
    ARG_MEDIA_SOURCE as ARG_EXTRACT_SOURCE,
    CMD_KB,
    HELP_OPTS,
    OPT_LLM,
    OPT_REASONING,
    OPT_RETRY_PROPOSE,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.knowledge import KnowledgeObject, validate_ids_exist
from lens.core.commands.kb import (
    kb_add,
    kb_extract,
    kb_template,
    kb_tag,
    kb_delete,
    kb_copy,
    kb_rename,
    kb_get,
    kb_list_tags,
    kb_with_tag,
    check_invalid_tags,
)
from lens.core.exceptions import LensException
from lens.core.project import find_project_root

app = typer.Typer(
    no_args_is_help=True,
    help=CMD_KB,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.command(no_args_is_help=True)
def add(
    id: str = typer.Argument(..., help=ARG_ID),
    content: str | None = typer.Argument(None, help=ARG_CONTENT_OPT),
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
    type_name: str = typer.Argument(..., help=ARG_TYPE_NAME),
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
    id: str = typer.Argument(..., help=ARG_ID),
) -> None:
    """Delete an object (file, tags, references)."""
    try:
        kb_delete(id)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def copy(
    source_id: str = typer.Argument(..., help=ARG_SOURCE_ID),
    target_id: str = typer.Argument(..., help=ARG_TARGET_ID),
) -> None:
    """Copy an object to a new ID. Target type may differ; directory is created if needed."""
    try:
        kb_copy(source_id, target_id)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command(no_args_is_help=True)
def rename(
    old_id: str = typer.Argument(..., help=ARG_OLD_ID),
    new_id: str = typer.Argument(..., help=ARG_NEW_ID),
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
    instruction: str = typer.Argument(..., help=ARG_INSTRUCTION),
    context: str | None = typer.Option(None, "--context", "-c", help="Narrative address with optional line slice (e.g. /chapter-1, /chapter-1 10, /chapter-1 10 30); with line bounds, no ancestor pin resolution"),
    include_template: bool = typer.Option(False, "--include-template", "-t", help="Include type template in prompt"),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(None, "--llm", "-l", help=OPT_LLM),
    reasoning: str | None = typer.Option(None, "--reasoning", help=OPT_REASONING),
    retry: bool = typer.Option(False, "--retry", "-r", help=OPT_RETRY_PROPOSE),
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
        _, cancelled = run_with_cancel(
            lambda cancel: _kb_edit_async(
                id=id,
                instruction=instruction,
                context_address=context,
                pins=list(pin),
                unpins=list(unpin),
                include_template=include_template,
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                on_token=_print_token,
                cancel_event=cancel,
            )
        )
        print()
        if cancelled:
            raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


async def _kb_edit_async(
    *,
    id: str,
    instruction: str,
    context_address: str | None,
    pins: list[str],
    unpins: list[str],
    include_template: bool,
    llm_id: str | None,
    reasoning: str | None,
    retry: bool,
    on_token: object,
    cancel_event: object,
) -> None:
    from lens.core.commands.kb import kb_edit as _kb_edit
    await _kb_edit(
        id,
        instruction,
        context_address=context_address,
        pins=pins,
        unpins=unpins,
        include_template=include_template,
        llm_id=llm_id,
        reasoning=reasoning,
        retry=retry,
        on_token=on_token,  # type: ignore[arg-type]
        cancel_event=cancel_event,  # type: ignore[arg-type]
    )


@app.command(no_args_is_help=True)
def get(
    ids: list[str] = typer.Argument(
        ...,
        help="Object ID(s); append + for one-hop linked objects, or ++ for full linked traversal",
    ),
    include_comments: bool = typer.Option(True, "--include-comments", help="Keep markdown comments in output"),
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


@app.command("list-tags")
def list_tags(
    type_filter: str | None = typer.Option(None, "--type", "-t", help=ARG_TYPE_FILTER),
    start_with: str | None = typer.Option(None, "--start-with", "-s", help=ARG_TAG_PREFIX),
) -> None:
    """List unique tag values, optionally filtered by type or prefix."""
    try:
        tags = kb_list_tags(type_filter=type_filter, prefix_filter=start_with)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    for tag in tags:
        typer.echo(tag)


@app.command("with-tag", no_args_is_help=True)
def with_tag(
    tags: list[str] = typer.Argument(
        ...,
        help=ARG_TAGS,
    ),
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
    type_filter: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Only return objects of this type (e.g. --type front)",
    ),
) -> None:
    """List object IDs matching tag groups (AND across, OR within parens); optionally expand or recurse by dot-tags."""
    if not tags:
        typer.echo("Error: at least one tag is required", err=True)
        raise typer.Exit(1)
    try:
        result = kb_with_tag(
            tags,
            expand=expand,
            recurse=recurse,
            same_type_only=same_type_only,
            type_filter=type_filter,
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

    def _format_id_with_tags(cid: str) -> str:
        if result.id_to_tags and cid in result.id_to_tags:
            tag_str = " ".join(result.id_to_tags[cid])
            return f"{cid}  [{tag_str}]" if tag_str else cid
        return cid

    if recurse is None:
        if not expand:
            for cid in result.ids:
                typer.echo(_format_id_with_tags(cid))
        else:
            for cid in result.ids:
                if result.objects and cid in result.objects:
                    _print_obj(result.objects[cid])
    else:
        if not expand:
            if result.ids or result.layers:
                typer.echo(f"# Objects with tag {tags[0]!r}")
                for cid in result.ids:
                    typer.echo(_format_id_with_tags(cid))
            if result.layers:
                for parent_tag, child_ids in result.layers:
                    typer.echo(f"\n> with-tag {parent_tag!r}")
                    for cid in child_ids:
                        typer.echo(_format_id_with_tags(cid))
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
    path: str = typer.Argument(..., help=ARG_EXTRACT_SOURCE),
) -> None:
    """Extract and upsert KB objects from structured markdown (single transaction).

    Each ```kb block must contain YAML front matter (delimited by ---) with an
    'id' field and optional 'tags' / 'remove-tags' lists. The block body becomes
    the object content when non-empty; if the body is empty or whitespace-only
    and the object already exists, only tags are updated (stored text unchanged).
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
