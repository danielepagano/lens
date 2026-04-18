from __future__ import annotations

import asyncio
import sys

import typer

from lens.cli.options import pin_option, reasoning_option, unpin_option
from lens.core.auto_compress import run_post_main_auto_compress_blocking_cli
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)

@app.callback()
def write(
    prompt: str | None = typer.Argument(
        None,
        help="Writing direction/instruction",
    ),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    reasoning: str | None = reasoning_option(),
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help="Discard generated text and regenerate",
    ),
    manual: str | None = typer.Option(
        None,
        "--manual",
        "-m",
        help="Append text directly to the cursor node without AI",
    ),
) -> None:
    """Generate narrative text at the cursor."""
    if prompt is None and manual is None and sys.stdin.isatty():
        typed = typer.prompt("Prompt", default="")
        if typed.strip():
            prompt = typed.strip()
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
        asyncio.run(
            WriteOperator.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                on_token=_print_token,
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

    run_post_main_auto_compress_blocking_cli(
        session,
        narrative,
        on_token=_print_token,
        on_status=lambda m: typer.echo(f"\nlens: {m}", err=True),
    )
