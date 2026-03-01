from __future__ import annotations

import asyncio

import typer

from lens.cli.utils import confirm_tool_call
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)

@app.callback()
def write(
    prompt: str | None = typer.Argument(
        None,
        help="Writing direction/instruction",
    ),
    pin: list[str] = typer.Option(
        [],
        "--pin",
        "-p",
        help="KB ID to pin for this operator (repeatable)",
    ),
    unpin: list[str] = typer.Option(
        [],
        "--unpin",
        "-u",
        help="KB ID to unpin for this operator (repeatable)",
    ),
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
        help="Discard generated text and regenerate",
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

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)

    try:
        asyncio.run(
            WriteOperator.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
                on_token=_print_token,
                on_confirm=confirm_tool_call,
            )
        )
        print() # ensure final newline
    except OperatorError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
