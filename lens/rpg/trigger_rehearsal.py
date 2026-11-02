"""Rehearse a trigger: does play actually write ``<!-- suggest:<slug> -->``?

``test-play`` runs a *reviewer* prompt in play's context, so it can say whether a
reader recognises a held-back moment. What it cannot say is whether **play's own
prompt** does: whether play, reaching the moment, stops at the threshold and
emits the marker. Until now that only showed up in real play.

A rehearsal is one real play beat, run in memory. It uses play's crawl at the
cursor, with a player line appended to the passage exactly where
``_append_player_line`` would write it (the ``lens explain -p`` route, so the two
cannot drift), and play's messages, tools and model profile. Then it reads back
which markers the beat emitted. **Nothing is written**: no node, no
transaction, no KB. ``repeat`` runs the same beat several times, because one
sample of a stochastic model says little.

Two things make it usable during prep, before the scene exists in the narrative:

- **targets** are pinned ``+`` in memory, exactly as test-play's review pins
  them, so a trigger on ``location.graysteps`` can be rehearsed before anything
  in the story pins it;
- **at** sets the scene: it is rendered as the GM's last passage before the
  player's line, so the beat starts *at* the moment instead of having to
  narrate its way there from wherever the cursor happens to be. Without it, a
  miss can mean play never reached the threshold, not that it ignored it.

A beat that ends without the marker is either a real miss (play went past the
moment) or play correctly stopping one step short, offering the moment as the
player's choice. ``then`` tells them apart: for such a beat it plays one more,
with that neutral line ("I go on." fits more stops than "Yes."), and a marker there means the first
beat had stopped short. It is opt-in, because a near-miss should be judged on
its first beat alone.

What a hit does **not** show: that play stopped at the threshold. The marker can
come after a paragraph describing what lies past it. Read the beats (``-v``).
And a high rate says nothing about spurious offers: pair each rehearsal with a
near-miss line, which should score zero.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lens.core.context import CrawlResult
from lens.core.exceptions import OperatorError, ValidationError
from lens.core.generation_artifacts import compose_for_operator
from lens.core.llm import LLMError
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.llm_trace import split_trace_blocks
from lens.core.module_requests import UNLOGGED_MODULE_TOOLS, ModuleRequestSink
from lens.core.narrative import NarrativeNode
from lens.core.operator_params import apply_pinned_invocation
from lens.core.project import ProjectSession, get_selected_datasets, operator_applies_to_session
from lens.core.prompts import run_prompt_overrides
from lens.core.triggers import find_trigger, suggested_slugs
from lens.rpg.operators.play import PlayOperator
from lens.rpg.operators.test_play import story_node

MAX_REPEAT = 10


@dataclass
class RehearsalRun:
    text: str = ""
    markers: list[str] = field(default_factory=list[str])
    interrupted: bool = False
    then_text: str | None = None
    """The follow-up beat, when ``then`` was given and the first had no marker."""
    then_markers: list[str] = field(default_factory=list[str])

    def hit(self, slug: str) -> bool:
        return slug in self.markers

    def hit_after(self, slug: str) -> bool:
        """No marker at first, the marker on the follow-up: it had stopped short."""
        return not self.hit(slug) and slug in self.then_markers

    def others(self, slug: str) -> list[str]:
        return [m for m in [*self.markers, *self.then_markers] if m != slug]

    def outcome(self, slug: str) -> str:
        if self.interrupted:
            return "interrupted"
        if self.hit(slug):
            return "suggested"
        if self.hit_after(slug):
            return "stopped-short"
        return "missed"


@dataclass
class RehearsalResult:
    slug: str
    when: str
    node: str
    player_line: str
    at: str = ""
    targets: list[str] = field(default_factory=list[str])
    then: str = ""
    runs: list[RehearsalRun] = field(default_factory=list[RehearsalRun])

    @property
    def hits(self) -> int:
        return sum(1 for run in self.runs if run.hit(self.slug))

    @property
    def hits_after(self) -> int:
        return sum(1 for run in self.runs if run.hit_after(self.slug))

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "when": self.when,
            "node": self.node,
            "player_line": self.player_line,
            "at": self.at,
            "targets": self.targets,
            "then": self.then,
            "hits": self.hits,
            "hits_after": self.hits_after,
            "runs": [
                {
                    "suggested": run.hit(self.slug),
                    "markers": run.markers,
                    "other_markers": run.others(self.slug),
                    "interrupted": run.interrupted,
                    "outcome": run.outcome(self.slug),
                    "text": run.text,
                    "then_text": run.then_text,
                    "then_markers": run.then_markers,
                }
                for run in self.runs
            ],
        }


def _join(base: str, block: str) -> str:
    sep = "" if not base.strip() else ("\n" if base.endswith("\n") else "\n\n")
    return base + sep + block


def _held_back_slugs(crawl_result: CrawlResult) -> list[str]:
    graph = crawl_result.render_graph
    if graph is None:
        return []
    for component in graph.components:
        if component.kind == "held_back":
            return [s for s in component.metadata.get("triggers", "").split(",") if s]
    return []


@dataclass
class RehearsalPlan:
    """Everything one rehearsal beat sends, assembled once and reused per run."""

    result: RehearsalResult
    messages: list[dict[str, str]]
    tools: Any
    handlers: Any
    resolved: Any
    ctx: Any
    llm_id: str | None
    reasoning: str | None


def prepare_rehearsal(
    *,
    session: ProjectSession,
    narrative: NarrativeNode,
    slug: str,
    prompt: str | None = None,
    targets: Sequence[str] = (),
    at: str | None = None,
    continuation: tuple[str, str] | None = None,
    llm_id: str | None = None,
    reasoning: str | None = None,
) -> RehearsalPlan:
    """Assemble play's beat for a rehearsal without calling a model.

    *prompt* is the player's line. It defaults to the trigger's ``when``, which
    states the event itself, so a default run is a smoke test (does play write
    the marker at all), not a test of recognising the moment. *targets* are KB
    ids pinned ``+`` in memory; *at* is a scene-setter rendered as the GM's last
    passage. *continuation* is ``(first beat, next player line)``: the beat
    already played, as a GM turn, then one more player line, for the follow-up.
    Inside a design session the beat is played where that session will return,
    its parent, which is where play would meet the moment.
    """
    if not operator_applies_to_session(
        get_selected_datasets(session.project_root), PlayOperator.limited_to_datasets
    ):
        raise ValidationError("rehearsing a trigger requires the rpg dataset")
    trig = find_trigger(session.kb, slug)
    node = story_node(narrative.find_cursor())
    llm_id, reasoning, _ = apply_pinned_invocation(
        slug=PlayOperator.name,
        project_root=session.project_root,
        focus_node=node,
        narrative=narrative,
        llm_id=llm_id,
        reasoning=reasoning,
        extra_params=None,
    )
    line = (prompt or trig.when).strip()
    ids = list(dict.fromkeys(t.strip().removesuffix("+") for t in targets if t.strip()))
    missing = [i for i in ids if not session.kb.exists(i)]
    if missing:
        raise ValidationError("KB object(s) not found: " + ", ".join(missing))
    scene = (at or "").strip()
    storage = session.new_storage(owner=None)
    params: dict[str, Any] = {}

    def _crawl(passage: str | None) -> tuple[CrawlResult, Any, Any]:
        extra: dict[str, Any] = {"storage": storage, "extra_pins": [f"{i}+" for i in ids]}
        if passage is not None:
            extra["current_passage_override"] = passage
        return PlayOperator.crawl_with_modalities(
            PlayOperator.crawl_spec(node, params, session=session, narrative=narrative, **extra),
            params,
            session=session,
            narrative=narrative,
        )

    crawl_result, _ctx, _resolved = _crawl(None)
    PlayOperator.check_requirements(crawl_result)
    line_block = PlayOperator.explain_prompt_line(line, crawl_result, params) or ""
    base = node.md_path().read_text(encoding="utf-8")
    if scene:
        # A closed play block is an assistant turn: the GM's last passage, so the
        # player's line answers a scene already standing at the moment.
        base = _join(base, f"[play]: #\n{scene}\n[/play]: #\n")
    passage = _join(base, line_block)
    if continuation is not None:
        beat, next_line = continuation
        passage = _join(passage, f"[play]: #\n{beat.strip()}\n[/play]: #\n")
        passage = _join(
            passage, PlayOperator.explain_prompt_line(next_line.strip(), crawl_result, params) or ""
        )
    crawl_result, ctx, resolved = _crawl(passage)
    op = PlayOperator(storage, narrative)
    messages = op.build_messages(
        crawl_result,
        params,
        session=session,
        narrative=narrative,
        resolved_modalities=resolved,
        passage_raw=passage,
    )
    held = _held_back_slugs(crawl_result)
    if trig.slug not in held:
        listed = ", ".join(held) if held else "none"
        raise ValidationError(
            f"{trig.slug} is not in play's [HELD BACK] at {node.path_str()} "
            f"(listed: {listed}). It is either done already or declared on "
            f"{trig.declared_on}, which is not in scope here: pass the scene's "
            f"object as an id (lens test-play {trig.declared_on} --trigger "
            f"{trig.slug}), or pin it in the narrative"
        )
    tools, handlers = PlayOperator.merge_command_tools_for_generation(
        resolved, ctx, session.project_root, params, module_sink=ModuleRequestSink()
    )
    return RehearsalPlan(
        result=RehearsalResult(
            slug=trig.slug,
            when=trig.when,
            node=node.path_str(),
            player_line=line,
            at=scene,
            targets=ids,
        ),
        messages=messages,
        tools=tools,
        handlers=handlers,
        resolved=resolved,
        ctx=ctx,
        llm_id=llm_id,
        reasoning=reasoning,
    )


async def rehearse_trigger(
    *,
    session: ProjectSession,
    narrative: NarrativeNode,
    slug: str,
    prompt: str | None = None,
    targets: Sequence[str] = (),
    at: str | None = None,
    then: str | None = None,
    repeat: int = 1,
    llm_id: str | None = None,
    reasoning: str | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    on_run_start: Callable[[int], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
    prompt_overrides: Mapping[str, str] | None = None,
) -> RehearsalResult:
    """:func:`_rehearse_trigger`, with *prompt_overrides* in force for this run only.

    The A/B arm of a prompt test: the override reaches every prompt read inside
    the run and nothing outside it (see :func:`~lens.core.prompts.run_prompt_overrides`).
    """
    with run_prompt_overrides(prompt_overrides):
        return await _rehearse_trigger(
            session=session,
            narrative=narrative,
            slug=slug,
            prompt=prompt,
            targets=targets,
            at=at,
            then=then,
            repeat=repeat,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            on_run_start=on_run_start,
            cancel_event=cancel_event,
        )


async def _rehearse_trigger(
    *,
    session: ProjectSession,
    narrative: NarrativeNode,
    slug: str,
    prompt: str | None = None,
    targets: Sequence[str] = (),
    at: str | None = None,
    then: str | None = None,
    repeat: int = 1,
    llm_id: str | None = None,
    reasoning: str | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    on_run_start: Callable[[int], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> RehearsalResult:
    """Run *repeat* in-memory play beats (see :func:`prepare_rehearsal`).

    With *then*, a beat that wrote no marker at all gets one follow-up beat with
    that player line, so "stopped one step short" reads apart from "went past".
    """
    if not 1 <= repeat <= MAX_REPEAT:
        raise ValidationError(f"repeat must be between 1 and {MAX_REPEAT}")
    plan = prepare_rehearsal(
        session=session,
        narrative=narrative,
        slug=slug,
        prompt=prompt,
        targets=targets,
        at=at,
        llm_id=llm_id,
        reasoning=reasoning,
    )
    result = plan.result
    follow = (then or "").strip()
    result.then = follow

    async def _beat(messages: list[dict[str, str]]) -> tuple[str, bool]:
        try:
            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    messages=messages,
                    llm_id=plan.llm_id,
                    reasoning=plan.reasoning,
                    tools=plan.tools,
                    command_tool_handlers=plan.handlers,
                    resolved_modalities=plan.resolved,
                    modality_context=plan.ctx,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    operator_name=PlayOperator.name,
                    unlogged_tool_names=UNLOGGED_MODULE_TOOLS,
                )
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e
        text, _traces = split_trace_blocks(compose_for_operator(artifacts, PlayOperator.name))
        return text.strip(), artifacts.interrupted

    for index in range(repeat):
        if on_run_start is not None:
            await on_run_start(index + 1)
        text, interrupted = await _beat(plan.messages)
        run = RehearsalRun(text=text, markers=suggested_slugs(text), interrupted=interrupted)
        if follow and not interrupted and not run.markers:
            second = prepare_rehearsal(
                session=session,
                narrative=narrative,
                slug=slug,
                prompt=prompt,
                targets=targets,
                at=at,
                continuation=(text, follow),
                llm_id=llm_id,
                reasoning=reasoning,
            )
            then_text, interrupted = await _beat(second.messages)
            run.then_text = then_text
            run.then_markers = suggested_slugs(then_text)
            run.interrupted = interrupted
        result.runs.append(run)
        if run.interrupted:
            break
    return result
