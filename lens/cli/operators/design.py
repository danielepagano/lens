from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.design import DesignOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False, no_args_is_help=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def design(
    prompt: str | None = typer.Argument(
        None,
        help="Design task or question",
    ),
    module: str | None = typer.Option(
        None,
        "--module",
        "-m",
        help="Design module key to use (KB object under design.<key>, e.g. 'encounter')",
    ),
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
        help="Retry (regenerate) the last design generation in the current session",
    ),
    end: bool = typer.Option(
        False,
        "--end",
        help="Close the current design session and extract KB entries",
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        "-s",
        help="Sub-node id to use when starting a new session (default: auto-generated from prompt)",
    ),
) -> None:
    """Collaborative KB design session: think, look up, and propose changes.

    The first call opens a new design sub-node.  Subsequent calls continue the
    current session.  Use --end to close the session and apply KB proposals.
    """
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

    if not end:
        try:
            ids_to_validate = list(pin) + list(unpin)
            module_key = module.strip() if module else None
            if module_key:
                ids_to_validate.append(f"design.{module_key}")
            validate_ids_exist(session.project_root, ids_to_validate)
        except LensException as e:
            typer.echo(f"lens design: {e}", err=True)
            raise typer.Exit(1)
    else:
        module_key = None

    try:
        result = asyncio.run(
            DesignOperator.run_design(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=module_key if not end else None,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
                end=end,
                slug=slug if not end and not retry else None,
                on_token=_print_token,
            )
        )
        if not end:
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
