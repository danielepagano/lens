from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.design import DesignOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def design(
    id: str = typer.Argument(
        ...,
        help="Design session ID (or 'end' to close current session; alphanumeric, underscores, hyphens)",
    ),
    prompt: str | None = typer.Argument(
        None,
        help="Design task or question",
    ),
    pin: list[str] = pin_option(),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Collaborative KB design session: think, look up, and propose changes. Use 'lens design end' to close the current session."""
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens design: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens design: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    if id.strip().lower() == "end":
        try:
            result = asyncio.run(
                DesignOperator.run_design_end(session=session, narrative=narrative)
            )
            if result.inserted:
                typer.echo(f"KB: inserted {', '.join(result.inserted)}")
            if result.updated:
                typer.echo(f"KB: updated {', '.join(result.updated)}")
            if result.errors:
                for err in result.errors:
                    typer.echo(f"lens design end: kb error: {err}", err=True)
        except OperatorError as e:
            typer.echo(f"lens design end: {e}", err=True)
            raise typer.Exit(1)
        return

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens design: {e}", err=True)
        raise typer.Exit(1)

    try:
        result = asyncio.run(
            DesignOperator.run_design(
                session=session,
                narrative=narrative,
                id=id,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                on_token=_print_token,
            )
        )
        print()  # final newline after streamed output
        if result.inserted:
            typer.echo(f"KB: inserted {', '.join(result.inserted)}")
        if result.updated:
            typer.echo(f"KB: updated {', '.join(result.updated)}")
        if result.errors:
            for err in result.errors:
                typer.echo(f"lens design: kb error: {err}", err=True)
    except OperatorError as e:
        typer.echo(f"lens design: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens design: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
