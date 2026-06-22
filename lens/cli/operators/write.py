from __future__ import annotations

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.cli.help_strings import (
    ARG_PROMPT_WRITE,
    OP_WRITE,
    OPT_LLM,
    OPT_MANUAL_WRITE,
    OPT_REASONING,
    OPT_RETRY,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=OP_WRITE,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)

@app.callback()
def write(
    prompt: str | None = typer.Argument(
        None,
        help=ARG_PROMPT_WRITE,
    ),
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
        help=OPT_RETRY,
    ),
    manual: str | None = typer.Option(
        None,
        "--manual",
        "-m",
        help=OPT_MANUAL_WRITE,
    ),
) -> None:
    """Generate narrative text at the cursor."""
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens write: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    if manual is not None:
        try:
            WriteOperator.run_manual(session=session, narrative=narrative, text=manual)
        except LensException as e:
            typer.echo(f"lens write: {e}", err=True)
            raise typer.Exit(1)
        return

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)

    try:
        _, cancelled = run_with_cancel(
            lambda cancel: WriteOperator.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                on_token=_print_token,
                cancel_event=cancel,
                on_status=lambda m: typer.echo(f"\nlens: {m}", err=True),
            )
        )
        print()  # ensure final newline
        if cancelled:
            raise typer.Exit(1)
    except OperatorError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
