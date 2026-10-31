from __future__ import annotations

import json

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.cli.help_strings import (
    ARG_IDS_TEST_PLAY,
    HELP_OPTS,
    OP_TEST_PLAY,
    OPT_JSON_TEST_PLAY,
    OPT_LLM,
    OPT_NO_SPINE_TEST_PLAY,
    OPT_PROMPT_TEST_PLAY,
    OPT_REASONING,
    OPT_VERBOSE_TEST_PLAY,
)
from lens.core.exceptions import LensException, OperatorError
from lens.core.project import ProjectSession
from lens.rpg.operators.test_play import TestPlayOperator

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=OP_TEST_PLAY,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def test_play(
    ids: list[str] = typer.Argument(None, help=ARG_IDS_TEST_PLAY),
    prompt: str | None = typer.Option(None, "--prompt", help=OPT_PROMPT_TEST_PLAY),
    no_spine: bool | None = typer.Option(
        None, "--no-spine/--spine", help=OPT_NO_SPINE_TEST_PLAY
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help=OPT_VERBOSE_TEST_PLAY),
    as_json: bool = typer.Option(False, "--json", help=OPT_JSON_TEST_PLAY),
    llm: str | None = typer.Option(None, "--llm", "-l", help=OPT_LLM),
    reasoning: str | None = typer.Option(None, "--reasoning", help=OPT_REASONING),
) -> None:
    """Review prepared content by reading and playing it as play would.

    The reviewer sees what play would see with the objects pinned: the rules,
    each object's + expansion and rules.<type> companions, the pinned PCs, and
    the story so far. It states what the GM would establish at the opening
    beat, plays three or four approaches through, and reports typed findings
    (contradiction, impossible, decided, ambiguous, gap, rules-error), each
    quoting the line it is about. It never rewrites anything.

    Inside a design session, with no ids it tests every object the session has
    proposals for, as proposed. The full review is written to a closed child of
    the session and the findings to the session itself, where the next design
    turn reads them. Anywhere else nothing is written: the findings are printed,
    and --verbose streams the whole review.
    """
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens test-play: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens test-play: no active narrative (run 'lens use <slug>' first)",
            err=True,
        )
        raise typer.Exit(1)

    stream = verbose and not as_json
    if not stream and not as_json:
        typer.echo("lens test-play: reviewing…", err=True)
    try:
        result, cancelled = run_with_cancel(
            lambda cancel: TestPlayOperator.run_test_play(
                session=session,
                narrative=narrative,
                targets=list(ids or []),
                prompt=prompt,
                no_spine=no_spine,
                llm_id=llm,
                reasoning=reasoning,
                on_token=_print_token if stream else None,
                cancel_event=cancel,
            )
        )
    except (OperatorError, LensException) as e:
        typer.echo(f"lens test-play: {e}", err=True)
        raise typer.Exit(1)

    if stream:
        print()
    if cancelled or result.interrupted:
        typer.echo("lens test-play: interrupted; nothing written", err=True)
        raise typer.Exit(1)

    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    if not stream:
        print(result.findings_text)
    if result.review_node is not None:
        typer.echo(
            f"lens test-play: full review in {result.review_node}; "
            "findings added to the design session",
            err=True,
        )
