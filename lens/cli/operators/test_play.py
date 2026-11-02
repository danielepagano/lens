from __future__ import annotations

import json
from pathlib import Path

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.cli.help_strings import (
    ARG_IDS_TEST_PLAY,
    OPT_AT_TEST_PLAY,
    HELP_OPTS,
    OP_TEST_PLAY,
    OPT_JSON_TEST_PLAY,
    OPT_LLM,
    OPT_NO_SPINE_TEST_PLAY,
    OPT_PROMPT_TEST_PLAY,
    OPT_REASONING,
    OPT_PROMPT_FILE_TEST_PLAY,
    OPT_REPEAT_TEST_PLAY,
    OPT_THEN_TEST_PLAY,
    OPT_TRIGGER_TEST_PLAY,
    OPT_VERBOSE_TEST_PLAY,
)
from lens.core.exceptions import LensException, OperatorError
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.prompts import load_prompt_override_files
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
    trigger: str | None = typer.Option(None, "--trigger", help=OPT_TRIGGER_TEST_PLAY),
    repeat: int = typer.Option(1, "--repeat", "-n", help=OPT_REPEAT_TEST_PLAY),
    at: str | None = typer.Option(None, "--at", help=OPT_AT_TEST_PLAY),
    then: str | None = typer.Option(None, "--then", help=OPT_THEN_TEST_PLAY),
    prompt_file: list[str] = typer.Option(
        [], "--prompt-file", help=OPT_PROMPT_FILE_TEST_PLAY
    ),
) -> None:
    """Review prepared content by reading and playing it as play would.

    The reviewer sees what play would see with the objects pinned: the rules,
    each object's + expansion and rules.<type> companions, the pinned PCs, and
    the story so far. It states what the GM would establish at the opening
    beat, plays one or two approaches through, and reports at most five typed
    findings (contradiction, impossible, decided, ambiguous, gap, rules-error),
    each quoting the line it is about. Only what the GM could not rule around
    counts; no findings is the usual result for prep that is ready. Run it once:
    fix contradictions, and cut or leave the rest to the GM rather than adding
    rules. It never rewrites anything.

    Inside a design session, with no ids it tests every object the session has
    proposals for, as proposed. The full review is written to a closed child of
    the session and the findings to the session itself, where the next design
    turn reads them. Anywhere else nothing is written: the findings are printed,
    and --verbose streams the whole review.

    With --trigger SLUG it rehearses that trigger instead. A review only shows
    that a reader recognises the moment; a rehearsal runs real play beats (play's
    prompt, model and tools) and reports whether play wrote <!-- suggest:SLUG -->.
    Nothing is written. Ids are pinned + in memory, so prep can be rehearsed
    before the scene is pinned anywhere; --at sets the scene as the GM's last
    passage; --prompt is the player's line. Use --repeat for a rate.

    Read the result with care. Without --prompt the line is the trigger's own
    'when', which only checks that play writes the marker at all. A hit does not
    show that play stopped at the threshold: read the beats with --verbose. And
    a high rate does not rule out spurious offers: pair every rehearsal with a
    near-miss line, which should score zero. A miss on both beats (with --then)
    is either play never getting there or play playing past the moment without
    the marker, which is the one that matters; only reading it with -v tells.
    A stopped-short pass needs the same read: the first beat should end one step
    before the moment, and the follow-up should stop at the threshold.
    A/B a prompt with --prompt-file KEY=FILE, which lasts for this run only.
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

    try:
        overrides = load_prompt_override_files(
            prompt_file, Path.cwd(), session.project_root
        )
    except ValueError as e:
        typer.echo(f"lens test-play: --prompt-file: {e}", err=True)
        raise typer.Exit(1)
    for key in overrides:
        typer.echo(f"lens test-play: {key} overridden for this run only", err=True)

    if trigger is not None:
        _rehearse(
            session, narrative, trigger, prompt, list(ids or []), at, then,
            repeat, verbose, as_json, llm, reasoning, overrides,
        )
        return
    if at is not None or then is not None:
        typer.echo("lens test-play: --at and --then only apply with --trigger", err=True)
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
                prompt_overrides=overrides,
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


def _rehearse(
    session: ProjectSession,
    narrative: NarrativeNode,
    slug: str,
    prompt: str | None,
    targets: list[str],
    at: str | None,
    then: str | None,
    repeat: int,
    verbose: bool,
    as_json: bool,
    llm: str | None,
    reasoning: str | None,
    overrides: dict[str, str],
) -> None:
    from lens.rpg.trigger_rehearsal import rehearse_trigger

    if not as_json:
        typer.echo(f"lens test-play: rehearsing {slug} ({repeat} beat(s))…", err=True)
    try:
        result, cancelled = run_with_cancel(
            lambda cancel: rehearse_trigger(
                session=session,
                narrative=narrative,
                slug=slug,
                prompt=prompt,
                targets=targets,
                at=at,
                then=then,
                repeat=repeat,
                llm_id=llm,
                reasoning=reasoning,
                cancel_event=cancel,
                prompt_overrides=overrides,
            )
        )
    except (OperatorError, LensException) as e:
        typer.echo(f"lens test-play: {e}", err=True)
        raise typer.Exit(1)
    if cancelled:
        typer.echo("lens test-play: interrupted; nothing written", err=True)
        raise typer.Exit(1)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    pinned = f" with {', '.join(t + '+' for t in result.targets)}" if result.targets else ""
    print(f"at {result.node}{pinned} — player: {result.player_line}")
    if result.at:
        print(f"scene: {result.at}")
    for index, run in enumerate(result.runs, start=1):
        outcome = run.outcome(result.slug)
        if outcome == "interrupted":
            verdict = "interrupted"
        elif outcome == "suggested":
            verdict = f"suggested {result.slug}  \u2713"
        elif outcome == "stopped-short":
            verdict = f"stopped short; suggested {result.slug} on the next beat  \u2713"
        elif run.markers or run.then_markers:
            verdict = "wrong marker  \u2717"
        elif run.then_text is not None:
            verdict = "no marker, nor on the next beat  \u2717"
        else:
            verdict = "no marker  \u2717"
        others = run.others(result.slug)
        extra = f"  (also: {', '.join(others)})" if others else ""
        print(f"run {index}: {verdict}{extra}")
        if verbose:
            print()
            print(run.text)
            if run.then_text is not None:
                print(f"\n> [then] {result.then}\n")
                print(run.then_text)
            print()
    after = f", +{result.hits_after} after one more beat" if result.then else ""
    tail = "" if verbose else " — read the beats with -v"
    print(f"{result.hits}/{len(result.runs)} suggested {result.slug}{after}{tail}")
