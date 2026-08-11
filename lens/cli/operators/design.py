from __future__ import annotations

import typer

from lens.cli.async_cancel import run_with_cancel

from lens.cli.help_strings import (
    ARG_PROMPT_DESIGN,
    OP_DESIGN,
    OPT_LLM,
    OPT_REASONING,
    OPT_RETRY_DESIGN,
    OPT_END_DESIGN,
    OPT_SLUG,
    OPT_PIN,
    OPT_UNPIN,
    OPT_MODULE_DESIGN,
    HELP_OPTS,
)
from lens.cli.options import (
    include_option,
    mention_option,
    pin_option,
    unpin_option,
)
from lens.core.exceptions import OperatorError, LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operators.design import DesignOperator
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    no_args_is_help=False,
    help=OP_DESIGN,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def design(
    prompt: str | None = typer.Argument(
        None,
        help=ARG_PROMPT_DESIGN,
    ),
    module: str | None = typer.Option(
        None,
        "--module",
        "-m",
        help=OPT_MODULE_DESIGN,
    ),
    pin: list[str] = pin_option(OPT_PIN),
    unpin: list[str] = unpin_option(OPT_UNPIN),
    mention: list[str] = mention_option(),
    include: list[str] = include_option(),
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
        help=OPT_RETRY_DESIGN,
    ),
    end: bool = typer.Option(
        False,
        "--end",
        help=OPT_END_DESIGN,
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        "-s",
        help=OPT_SLUG,
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
            ids_to_validate = list(pin) + list(unpin) + list(mention) + list(include)
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
        result, cancelled = run_with_cancel(
            lambda cancel: DesignOperator.run_design(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=module_key if not end else None,
                pins=list(pin),
                unpins=list(unpin),
                mentions=list(mention),
                includes=list(include),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                end=end,
                slug=slug if not end and not retry else None,
                on_token=_print_token,
                cancel_event=cancel,
            )
        )
        if not end:
            print()  # final newline after streamed output
        if cancelled:
            raise typer.Exit(1)
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
