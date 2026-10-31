"""Test-play operator: review prepared content by reading and playing it as play would.

``lens test-play [ID…]`` hands one or more KB objects to a reviewer that sees
exactly what ``play`` would see with them pinned, and asks it for two things in
one call: a **cold read** of what the GM would establish at the opening beat,
and **playthroughs** of three or four distinct approaches against the objects'
own rules.  It reports typed findings, each citing the line it is about.  It
never rewrites and never gates anything: the user decides what happens next.

The operator persists as ``test_play`` because the annotation grammar has no
``-`` in operator names; the CLI command and the UI say ``test-play``.

What it tests
-------------
*  Inside an open ``design`` session the draft is the session's **proposals**:
   ``[kb-op]`` blocks folded into the pending layer, so they read like any
   object.  With no id, the targets are every object the session has proposals
   for; a session that has only *talked* about an object has nothing to test.
*  Anywhere else it tests what is on disk, and an id is required.

What it reads
-------------
The context ``play`` would assemble with the targets pinned (``<id>+``):
``rules.system`` and ``rules.rpg`` (the ``rpg_play_context`` modality), the
``+`` expansion, ``rules.<type>`` companions, and the ``pc.*`` pins in scope.
No ``-`` facets — ``expand_facets`` stays off, as it is for ``play`` — and the
only tool is play's own ``load_module`` catalog.  No KB writes.

The story is the spine ``play`` would read: up to the design session's parent
inside a session, up to the cursor outside one.  The design session's own text
is prep talk, not story, and is never crawled — :func:`story_node` walks out of
every enclosing design session.  ``--no-spine`` drops the narrative entirely;
``--prompt`` states assumed circumstances, which the reviewer is told override
the spine where they conflict.

Where the output goes
---------------------
*  Inside a design session: a **sub-node of the session, closed in the same
   call**.  The full review lands in the child; the session node gets the
   canonical summary block whose body is the review's own findings list — no
   second summarize call, which would cost a call and could soften a finding.
*  Anywhere else: nothing is written.  The result is returned for the CLI or the
   UI to show.

Why the review is generated *before* the child opens
----------------------------------------------------
The pending layer is folded from the **cursor node only**, and opening a child
moves the cursor into it, so a review generated inside the child would see the
draft vanish unless the session's ops were re-seeded through an in-flight sink.
Generating first, while the cursor still sits on the session node, needs no
seeding at all, and it is failure-atomic as well: a cancelled or failed review
leaves nothing behind, where a child opened first would leave an unclosed
``[test_play:…]`` tag holding the cursor until someone rewound it.  The child is
then created, filled and closed in one write sequence.
"""

from __future__ import annotations

import asyncio
import re
import tomllib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, cast

from lens.core.context import CrawlResult, CrawlSpec, assemble_prompt
from lens.core.exceptions import OperatorError, ValidationError
from lens.core.generation_artifacts import GenerationArtifacts, compose_for_operator
from lens.core.kb_pending import parse_kb_ops
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.llm_trace import split_trace_blocks
from lens.core.modalities import apply_modality_crawl
from lens.core.modalities.apply import merge_modality_command_tools
from lens.core.module_requests import (
    UNLOGGED_MODULE_TOOLS,
    ModuleDecl,
    ModuleRequestSink,
    build_module_request_bundle,
    unloaded_modules,
)
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator
from lens.core.operator_params import apply_pinned_invocation
from lens.core.operators.session import format_summary_block, prompt_to_slug
from lens.core.prompts import PromptStore
from lens.core.project import (
    ProjectSession,
    get_selected_datasets,
    operator_applies_to_session,
)

PLAY_OPERATOR = "play"
"""The reader under test.  Its module catalog and LLM profile are the defaults."""

DESIGN_OPERATOR = "design"

FINDING_KINDS: tuple[str, ...] = (
    "contradiction",
    "impossible",
    "decided",
    "ambiguous",
    "gap",
    "rules-error",
)
"""Finding types, in the order the prompt lists them.  ``impossible`` covers
"impossible or dead": a rule or trigger that cannot happen, or never matters."""

_FINDINGS_HEADING = re.compile(r"^(#{1,6})\s*findings\b.*$", re.IGNORECASE)
_ANY_HEADING = re.compile(r"^(#{1,6})\s+\S")
_FINDING_BULLET = re.compile(
    r"^\s*[-*]\s+[*_`\[]*\s*(" + "|".join(re.escape(k) for k in FINDING_KINDS) + r")\b",
    re.IGNORECASE,
)

MAX_TITLE_IDS = 3
"""Summary titles name up to this many targets; more are counted instead."""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    kind: str
    text: str


@dataclass
class TestPlayResult:
    """What one review produced.

    *review_node* is the address of the closed child holding the full review,
    or ``None`` when nothing was written (outside a design session, or the
    review was interrupted).
    """

    __test__: ClassVar[bool] = False

    targets: list[str]
    review: str = ""
    findings_text: str = ""
    findings: list[Finding] = field(default_factory=list[Finding])
    review_node: str | None = None
    interrupted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "findings": [{"kind": f.kind, "text": f.text} for f in self.findings],
            "findings_text": self.findings_text,
            "review": self.review,
            "review_node": self.review_node,
            "interrupted": self.interrupted,
        }


# ---------------------------------------------------------------------------
# Findings extraction
# ---------------------------------------------------------------------------


def extract_findings(review: str) -> tuple[str | None, list[Finding]]:
    """The review's ``Findings`` section, verbatim, and the typed bullets in it.

    The section runs from its heading to the next heading of the same or a
    higher level.  ``None`` when the review has no such heading; a section that
    says there is nothing to report returns its text and an empty list.
    """
    lines = review.split("\n")
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = _FINDINGS_HEADING.match(line.strip())
        if m:
            start, level = i + 1, len(m.group(1))
    if start is None:
        return None, []
    end = len(lines)
    for j in range(start, len(lines)):
        m = _ANY_HEADING.match(lines[j].strip())
        if m and len(m.group(1)) <= level:
            end = j
            break
    section = "\n".join(lines[start:end]).strip()

    findings: list[Finding] = []
    current: list[str] = []
    kind = ""
    for line in section.split("\n"):
        m = _FINDING_BULLET.match(line)
        if m:
            if current:
                findings.append(Finding(kind, "\n".join(current).strip()))
            kind = m.group(1).lower()
            current = [line.strip()]
        elif current and line.strip() and line.startswith((" ", "\t")):
            current.append(line.strip())
        elif current:
            findings.append(Finding(kind, "\n".join(current).strip()))
            current = []
    if current:
        findings.append(Finding(kind, "\n".join(current).strip()))
    return section, findings


def target_ids(params: dict[str, Any]) -> list[str]:
    """``params["targets"]`` as a list of ids, whatever shape it was stored in."""
    raw = params.get("targets")
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [str(t) for t in cast(list[object], raw)]


def summary_title(targets: Sequence[str]) -> str:
    if len(targets) <= MAX_TITLE_IDS:
        return "Test-play findings: " + ", ".join(targets)
    return f"Test-play findings: {len(targets)} objects"


# ---------------------------------------------------------------------------
# Where the story is, and what the draft is
# ---------------------------------------------------------------------------


def _parent(node: NarrativeNode) -> NarrativeNode:
    return NarrativeNode(narrative_root=node.narrative_root, key_path=node.key_path[:-1])


def is_design_session_node(node: NarrativeNode) -> bool:
    """True when *node* is the sub-node of a still-open ``design`` session."""
    if not node.key_path:
        return False
    try:
        parent_text = _parent(node).md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    ann = find_unclosed_cursor_annotation(parent_text)
    return (
        ann is not None
        and ann.operator == DESIGN_OPERATOR
        and ann.id == node.key_path[-1]
    )


def story_node(node: NarrativeNode) -> NarrativeNode:
    """The node whose spine is the story: *node*, outside every open design session."""
    while is_design_session_node(node):
        node = _parent(node)
    return node


def proposed_ids(text: str, store: KnowledgeStore) -> list[str]:
    """Objects a design session node proposes, in the order it first touched them.

    An id the session later removed is dropped, and so are ``_template``-style
    keys: a template is the shape of an object, not something play runs.
    """
    layer = store.pending_layer()
    live = (set(layer.objects) | set(layer.tags)) - layer.removed
    out: list[str] = []
    for op in parse_kb_ops(text):
        ids = [op.id] if op.id else list(op.ids)
        for cid in ids:
            key = cid.partition(".")[2]
            if cid in live and cid not in out and not key.startswith("_"):
                out.append(cid)
    return out


def llm_profile_name(project_root: Path) -> str:
    """``test_play`` when the project configures it, else play's profile.

    The reader under test is play's model, so ``[operator.play]`` is the default;
    an explicit ``[operator.test_play]`` section wins over it wholesale.
    """
    try:
        with (project_root / "lens.toml").open("rb") as f:
            config = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return PLAY_OPERATOR
    operators = config.get("operator", {})
    if isinstance(operators, dict) and TestPlayOperator.name in operators:
        return TestPlayOperator.name
    return PLAY_OPERATOR


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class TestPlayOperator(Operator):
    __test__: ClassVar[bool] = False  # not a pytest class, whatever the name says

    name: ClassVar[str] = "test_play"
    requires_id: ClassVar[bool] = True
    limited_to_datasets: ClassVar[list[str]] = ["rpg"]
    required_modalities: ClassVar[frozenset[str]] = frozenset({"rpg_play_context"})
    # The hint lists play's catalog; the tool is built in :meth:`_tools` for the
    # same reason, since the base helpers key the catalog on ``cls.name``.
    supports_module_requests: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("test_play.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompts = PromptStore(self.project_root)
        targets = target_ids(params)
        circumstances = str(params.get("prompt") or "").strip()
        instruction = prompts.format(
            "test_play.instruction",
            targets=", ".join(f"`{t}`" for t in targets) or "(none)",
        )
        if circumstances:
            instruction += prompts.format(
                "test_play.circumstances_suffix", circumstances=circumstances
            )
        if params.get("no_spine"):
            instruction += prompts.get("test_play.no_spine_suffix")
        return instruction

    # ------------------------------------------------------------------
    # Context: play's, around the story node
    # ------------------------------------------------------------------

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        design_pins = sorted(p for p in crawl_result.pinned_ids if p.startswith("design."))
        if design_pins:
            raise ValidationError(
                "test-play reads what play reads, and play refuses to run with design "
                "modules pinned (" + ", ".join(design_pins) + "); unpin them first"
            )

    @classmethod
    def crawl_spec(
        cls,
        node: NarrativeNode,
        params: dict[str, Any],
        *,
        session: ProjectSession | None,
        narrative: NarrativeNode,
        **kwargs: Any,
    ) -> CrawlSpec:
        """Play's crawl, around the story node, with the targets pinned ``+``.

        *node* is where the user stands (the design session node, or the cursor).
        The crawl itself runs on :func:`story_node`, so the session's own prep
        talk never reaches the reviewer.  Targets come from ``params["targets"]``;
        without them (``lens explain -o test_play``) they default to the
        session's proposals, so the report shows what a bare run would send.
        """
        story = story_node(node)
        targets = target_ids(params)
        if not targets and story.key_path != node.key_path:
            store = (
                session.kb
                if session is not None
                else KnowledgeStore.for_project(narrative.narrative_root.parent.parent)
            )
            targets = proposed_ids(node.md_path().read_text(encoding="utf-8"), store)
            params["targets"] = targets
        extra_pins = [*(kwargs.pop("extra_pins", None) or ()), *(f"{t}+" for t in targets)]
        if story.key_path != node.key_path:
            # A passage cut is a line in the node the user named, not in the story.
            kwargs.pop("current_passage_override", None)
        if params.get("no_spine"):
            kwargs["include_narrative"] = False
        return super().crawl_spec(
            story,
            params,
            session=session,
            narrative=narrative,
            extra_pins=extra_pins,
            **kwargs,
        )

    def append_module_hint(self, crawl_result: CrawlResult, instruction: str) -> str:
        decls = self._play_modules(crawl_result)
        if not decls:
            return instruction
        prompts = PromptStore(self.project_root)
        catalog = "\n".join(
            prompts.format(
                "shared.module_request_catalog_entry",
                id=d.kb_id,
                description=d.description,
            )
            for d in decls
        )
        hint = prompts.format("test_play.module_hint", catalog=catalog)
        return f"{instruction.rstrip()}\n\n{hint}"

    @staticmethod
    def _play_modules(crawl_result: CrawlResult) -> tuple[ModuleDecl, ...]:
        if crawl_result.project_root is None:
            return ()
        return unloaded_modules(crawl_result.project_root, PLAY_OPERATOR, crawl_result)

    def build_messages(
        self,
        crawl_result: CrawlResult,
        params: dict[str, Any],
        *,
        session: ProjectSession | None = None,
        narrative: NarrativeNode | None = None,
        resolved_modalities: Any | None = None,
        passage_raw: str | None = None,
    ) -> list[dict[str, str]]:
        """One review request: no passage turns, no modality addenda.

        The base flow replays earlier play blocks as assistant turns, which is
        right for a GM continuing a scene and wrong for a reviewer reading one:
        the story is context here, rendered whole in ``[CURRENT PASSAGE]``.  The
        built-in addenda are emit rules for prose that lands in a node ("no
        headers", ``<!-- ai: -->`` conventions); a review is not that, and its
        format is set by ``test_play.instruction``.  Modalities still shape the
        crawl, which is where ``rpg_play_context`` does its work.
        """
        del passage_raw
        ctx, resolved = self._modality_context(
            crawl_result, params, session=session, narrative=narrative
        )
        if resolved_modalities is not None:
            resolved = resolved_modalities
        apply_modality_crawl(crawl_result, resolved, ctx)
        instruction = self.append_module_hint(crawl_result, self.build_instruction(params))
        return assemble_prompt(
            crawl_result, system_prompt=self.system_prompt, instruction=instruction
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @classmethod
    async def run_test_play(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        targets: Sequence[str] = (),
        prompt: str | None = None,
        no_spine: bool = False,
        llm_id: str | None = None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> TestPlayResult:
        """Review *targets* (or the open design session's proposals) once."""
        if not operator_applies_to_session(
            get_selected_datasets(session.project_root), cls.limited_to_datasets
        ):
            raise ValidationError("test-play requires the rpg dataset")
        cursor = narrative.find_cursor()
        in_design = is_design_session_node(cursor)
        store = session.kb
        # Pinned ``params.test_play`` fill what the caller left out, exactly as
        # ``lens explain -o test_play`` reads them, so the two cannot disagree.
        llm_id, reasoning, pinned = apply_pinned_invocation(
            slug=cls.name,
            project_root=session.project_root,
            focus_node=cursor,
            narrative=narrative,
            llm_id=llm_id,
            reasoning=reasoning,
            extra_params=None,
        )
        if not targets:
            targets = target_ids(pinned)
        if prompt is None and isinstance(pinned.get("prompt"), str):
            prompt = pinned["prompt"]
        no_spine = no_spine or pinned.get("no_spine") is True

        ids = [t.strip().removesuffix("+") for t in targets if t.strip()]
        ids = list(dict.fromkeys(ids))
        if not ids:
            if not in_design:
                raise ValidationError(
                    "test-play needs a KB id outside a design session "
                    "(lens test-play <id>)"
                )
            ids = proposed_ids(cursor.md_path().read_text(encoding="utf-8"), store)
            if not ids:
                raise ValidationError(
                    "nothing to test: this design session has not proposed any "
                    "object yet (an object it has only discussed is not a draft)"
                )
        missing = [i for i in ids if not store.exists(i)]
        if missing:
            raise ValidationError("KB object(s) not found: " + ", ".join(missing))

        params: dict[str, Any] = {"targets": ids}
        circumstances = (prompt or "").strip()
        if circumstances:
            params["prompt"] = circumstances
        if no_spine:
            params["no_spine"] = True
        if reasoning:
            params["reasoning"] = reasoning

        probe = cls(session.new_storage(owner=None), narrative)
        crawl_result, ctx, resolved = cls.crawl_with_modalities(
            cls.crawl_spec(cursor, params, session=session, narrative=narrative),
            params,
            session=session,
            narrative=narrative,
        )
        cls.check_requirements(crawl_result)
        messages = probe.build_messages(
            crawl_result,
            params,
            session=session,
            narrative=narrative,
            resolved_modalities=resolved,
        )
        module_sink = ModuleRequestSink()
        tools, handlers = merge_modality_command_tools(
            *cls._tools(crawl_result, module_sink, session.project_root),
            resolved,
            ctx,
        )

        try:
            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    messages=messages,
                    llm_id=llm_id,
                    reasoning=reasoning,
                    enable_thinking=True,
                    tools=tools,
                    command_tool_handlers=handlers,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    on_stream_event=on_stream_event,
                    operator_name=llm_profile_name(session.project_root),
                    unlogged_tool_names=UNLOGGED_MODULE_TOOLS,
                )
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        result = TestPlayResult(targets=ids)
        if artifacts.interrupted:
            result.interrupted = True
            return result
        if not artifacts.has_content():
            raise OperatorError("no review generated")

        composed = compose_for_operator(artifacts, cls.name)
        review, _traces = split_trace_blocks(composed)
        result.review = review.strip()
        section, findings = extract_findings(result.review)
        result.findings = findings
        if section is None:
            # A review that ignored the format still cost a call: hand the whole
            # thing on rather than nothing, and say why.
            result.findings_text = PromptStore(session.project_root).format(
                "test_play.no_findings_section", review=result.review
            ).strip()
        else:
            result.findings_text = section or "No findings."

        if in_design:
            result.review_node = cls._write_review(
                session=session,
                narrative=narrative,
                design_node=cursor,
                params=params,
                artifacts=artifacts,
                findings_text=result.findings_text,
                module_sink=module_sink,
            )
        return result

    @classmethod
    def _tools(
        cls,
        crawl_result: CrawlResult,
        sink: ModuleRequestSink,
        project_root: Path,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
        bundle = build_module_request_bundle(
            cls._play_modules(crawl_result), sink, project_root
        )
        if bundle is None:
            return None, None
        return bundle.tools, dict(bundle.handlers or {})

    @classmethod
    def review_node_id(cls, targets: Sequence[str], parent: NarrativeNode) -> str:
        """``test-play-<first target key>``, numbered when a sibling has it."""
        first = targets[0].partition(".")[2] if targets else ""
        slug = prompt_to_slug(first.replace("_", " ").replace("-", " "))
        base = f"test-play-{slug}" if slug else "test-play"
        existing = set(parent.child_keys())
        if base not in existing:
            return base
        n = 1
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    @classmethod
    def _write_review(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        design_node: NarrativeNode,
        params: dict[str, Any],
        artifacts: GenerationArtifacts,
        findings_text: str,
        module_sink: ModuleRequestSink,
    ) -> str:
        """Child with the full review, closed at once; findings on the session node."""
        targets = target_ids(params)
        child_id = cls.review_node_id(targets, design_node)
        rel_path = str(design_node.md_path().relative_to(session.git_root))
        storage = session.new_storage(owner=cls.owner_id(child_id, rel_path))
        op = cls(storage, narrative)

        child = op.create_subnode(design_node, child_id)
        block_params = {k: v for k, v in params.items() if k != "reasoning"}
        op.write_start(
            child,
            op.build_open_tag(None, block_params),
            artifacts=artifacts,
            pre_tag_text=module_sink.include_annotations(),
        )

        body = findings_text
        circumstances = str(params.get("prompt") or "").strip()
        if circumstances:
            body = PromptStore(session.project_root).format(
                "test_play.summary_circumstances", circumstances=circumstances
            ) + "\n\n" + body
        summary = format_summary_block(child_id, f"{summary_title(targets)}\n\n{body}")
        op.close_subnode(design_node, child_id, summary)
        return str(child.to_address())
