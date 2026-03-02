from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operators.edit import EditOperator
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession, resolve_address

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)

async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)

@app.callback()
def edit(
    ctx: typer.Context,
    address: str | None = typer.Argument(None, help="Narrative node address"),
    start_line: int | None = typer.Argument(None, help="First line to edit (1-based, inclusive)"),
    end_line: int | None = typer.Argument(None, help="Last line to edit (1-based, inclusive)"),
    prompt: str | None = typer.Argument(None, help="Editing instruction"),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help="Re-propose with same or updated parameters",
    ),
) -> None:
    """Rewrite a line range in a narrative node using the LLM."""
    if address is None or start_line is None or end_line is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens edit: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens edit: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens edit: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)

    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(session.git_root))
    ann_id = EditOperator.ann_id(start_line, end_line)

    try:
        asyncio.run(
            EditOperator.run_mutation(
                session=session,
                node=target_node,
                rel_path=rel_path,
                ann_id=ann_id,
                start_line=start_line,
                end_line=end_line,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
                on_token=_print_token,
            )
        )
        print() # ensure final newline
    except OperatorError as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
