from __future__ import annotations

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.cli.options import pin_option, unpin_option
from lens.core.compression import Aggressiveness
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.llm import LLMError
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession
from lens.core.operators.compress import CompressNoCollate, run_compress
from lens.core.workflow_runner import WorkflowOutcome


app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Use AI to pick a range on the cursor node and collate it into a child section "
        "(provide a PROMPT or --aggressiveness)."
    ),
    add_completion=False,
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens compress: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def compress(
    ctx: typer.Context,
    prompt: str | None = typer.Argument(
        None,
        metavar="PROMPT",
        help="What to collate (omit if using --aggressiveness)",
    ),
    node: str | None = typer.Option(
        None,
        "--node",
        "-n",
        help="Narrative node address (default: cursor, same as lens pin kb)",
    ),
    pin: list[str] = pin_option("KB ID to pin for collate summary context (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin (repeatable)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help="Reasoning override: none, low, medium, high",
    ),
    summary_guide: str | None = typer.Option(
        None,
        "--summary-guide",
        "-g",
        help="Optional extra instructions for the collate summary LLM",
    ),
    aggressiveness: Aggressiveness | None = typer.Option(
        None,
        "--aggressiveness",
        "-a",
        help="Without a prompt: low | medium | high (automated range selection)",
    ),
) -> None:
    """Pick a range via AI (compress_collate tool) then collate at the cursor or --node."""
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    stripped_arg = (prompt or "").strip()
    has_prompt = bool(stripped_arg)
    if has_prompt and aggressiveness is not None:
        typer.echo("lens compress: pass a PROMPT or --aggressiveness, not both", err=True)
        raise typer.Exit(1)
    if not has_prompt and aggressiveness is None:
        typer.echo(
            "lens compress: provide a PROMPT or --aggressiveness (low|medium|high)",
            err=True,
        )
        raise typer.Exit(1)
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    try:
        rc, cancelled = run_with_cancel(
            lambda cancel: run_compress(
                session=session,
                narrative=narrative,
                prompt=stripped_arg if has_prompt else None,
                aggressiveness=aggressiveness if not has_prompt else None,
                address=node,
                pins=pin,
                unpins=unpin,
                llm_id=llm,
                reasoning=reasoning,
                summary_guide=summary_guide,
                on_token=_print_token,
                cancel_event=cancel,
            )
        )
        print()
        if cancelled or isinstance(rc, WorkflowOutcome):
            typer.echo("lens compress: interrupted before collate", err=True)
            raise typer.Exit(1)
        if isinstance(rc, CompressNoCollate):
            typer.echo(rc.explanation or "compress: model did not collate", err=True)
            raise typer.Exit(1)
    except OperatorError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens compress: LLM error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo("Compress finished (collate applied at cursor).", err=True)
