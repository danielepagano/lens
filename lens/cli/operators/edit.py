from __future__ import annotations

import typer

from lens.cli.async_cancel import run_with_cancel

from lens.cli.help_strings import (
    ARG_ADDRESS_EDIT,
    ARG_LINE_1,
    ARG_PROMPT_EDIT,
    OP_EDIT,
    OPT_LLM,
    OPT_REASONING,
    OPT_RETRY_PROPOSE,
    OPT_REPLACE,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operators.edit import EditOperator
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession, resolve_address

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    add_completion=False,
    help=OP_EDIT,
    context_settings={"help_option_names": HELP_OPTS},
)

async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)

@app.callback()
def edit(
    ctx: typer.Context,
    address: str | None = typer.Argument(None, help=ARG_ADDRESS_EDIT),
    start_line: int | None = typer.Argument(None, help=ARG_LINE_1),
    end_line: int | None = typer.Argument(None, help=ARG_LINE_1),
    prompt: str | None = typer.Argument(None, help=ARG_PROMPT_EDIT),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help=OPT_LLM,
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help=OPT_REASONING,
    ),
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help=OPT_RETRY_PROPOSE,
    ),
    replace: bool = typer.Option(
        False,
        "--replace",
        help=OPT_REPLACE,
    ),
) -> None:
    """Rewrite a line range in a narrative node using the LLM, or replace it directly."""
    if address is None or start_line is None or end_line is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    if replace and retry:
        typer.echo("lens edit: --retry is not supported together with --replace", err=True)
        raise typer.Exit(1)

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
        _, cancelled = run_with_cancel(
            lambda cancel: EditOperator.run_mutation(
                session=session,
                node=target_node,
                rel_path=rel_path,
                ann_id=ann_id,
                start_line=start_line,
                end_line=end_line,
                prompt=prompt,
                manual=replace,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                on_token=_print_token,
                cancel_event=cancel,
            )
        )
        print()  # ensure final newline
        if cancelled:
            raise typer.Exit(1)
    except OperatorError as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
