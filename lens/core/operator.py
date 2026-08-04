"""Extensible operator base class for Lens.

Operators are the units that manipulate narrative text and structure via
traceable annotation patterns (e.g. ``[write]: #``, ``[section:ch1]: #``).
Each subclass declares a ``name`` and ``requires_id``; the base class provides
tag builders, annotation readers, node write helpers, and flow orchestration
for the three modes below. Storage is always tied to an *owner address* so the
storage layer can enforce single-pending-transaction semantics.

-------------------------------------------------------------------------------
Operating modes
-------------------------------------------------------------------------------

1. **Inline** (write, play): append at the narrative cursor. One open
   annotation per operator per cursor node; calling again continues, retries,
   or update-retries that same annotation.

2. **Sub-node** (section): create a child node and append an open tag to the
   parent; the operator then runs at the child cursor.

3. **Mutation** (edit): wrap a line range in claim tags and stream a proposed
   replacement as an unstaged diff.

-------------------------------------------------------------------------------
Inline flow: run_inline → which path?
-------------------------------------------------------------------------------

Entry is :meth:`run_inline` (CLI or another operator's tool invoke_fn).
It resolves the cursor, checks for an existing open annotation of this
operator, and decides:

- **No existing annotation** → :meth:`_do_fresh_inline`
- **Existing annotation, same owner, ``--retry``** → :meth:`_do_retry`
  (discard + regenerate, optionally with updated params)
- **Existing annotation, same owner, new prompt/pins/llm (no ``--retry``)** →
  auto-commit pending, then :meth:`_do_fresh_inline`
- **Existing annotation, same owner, no new args** →
  :meth:`_do_continue` (append to existing content)

-------------------------------------------------------------------------------
Fresh inline: _do_fresh_inline step-by-step
-------------------------------------------------------------------------------

1. **Build ann_params**  
   From prompt, pins, unpins, llm_id, and **extra_params** (generic dict
   from the caller; base class just merges it). Subclasses can pass
   operator-specific keys (e.g. play passes ``as_pc`` via extra_params).

2. **Crawl**  
   :func:`~lens.core.context.crawl` with cursor and extra_pins/extra_unpins
   → :class:`~lens.core.context.CrawlResult` (knowledge, summaries,
   current_content, pinned_ids).

3. **Requirements and param enrichment**  
   :meth:`check_requirements`(crawl_result) — override to raise if e.g. pins
   are missing.  
   :meth:`enrich_params`(crawl_result, ann_params) — override to derive
   params from crawl result and/or extra_params (e.g. play resolves
   ``as_pc`` against pinned_ids, sets ``pc_key``, pops ``as_pc`` so it
   isn't stored in the tag).

4. **Build tag and messages**  
   Open tag is built from ann_params (so stored annotation reflects
   enriched params). Messages come from :meth:`build_messages` (default:
   :func:`~lens.core.context.assemble_prompt` with system_prompt and
   :meth:`build_instruction`(ann_params)).

5. **Generate**
   :func:`~lens.core.llm_run.run_llm` with optional tools. Result is
   :class:`~lens.core.generation_artifacts.GenerationArtifacts` (or a native
   tool call via :func:`~lens.core.llm_run.run_llm_final` for tool-first flows).

6. **Normal path**  
   No tool call (or unknown tool): :meth:`content_prefix_for_fresh`(ann_params)
   can prepend text (e.g. play's ``> [Alice] prompt\\n\\n``), then
   :meth:`write_start`(cursor, tag, content) appends open tag + content +
   close tag.

-------------------------------------------------------------------------------
Continue / retry / update-retry
-------------------------------------------------------------------------------

- **Continue**: crawl with existing ann params, build_messages, stream,
  :meth:`write_append` (no new tag).

- **Retry**: discard current content, re-crawl with existing params, stream,
  content_prefix_for_fresh + write_append.

- **Update-retry**: merge new prompt/pins/unpins/llm_id/extra_params into
  existing params, discard, re-crawl, enrich_params (so update-retry also
  runs enrichment), stream, content_prefix + write_append.

-------------------------------------------------------------------------------
Subclass integration points
-------------------------------------------------------------------------------

- **Class vars**: ``name``, ``requires_id``, ``limited_to_datasets``,
  ``use_command_tools``.

- **Required**: :meth:`system_prompt`, :meth:`build_instruction`(params).

- **Optional**: :meth:`check_requirements`(crawl_result),
  :meth:`enrich_params`(crawl_result, params),
  :meth:`content_prefix_for_fresh`(params),
  :meth:`build_messages`(crawl_result, params) (default uses
  assemble_prompt with instruction from build_instruction).


"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal, cast
from collections.abc import Callable, Awaitable
import yaml


from lens.core.address import NarrativeAddress
from lens.core.annotations import (
    ParsedAnnotation,
    parse_annotations,
    strip_markdown_comments,
)
from lens.core.command_tools import CommandToolFn
from lens.core.context import (
    CrawlResult,
    CrawlSpec,
    apply_transforms_to_result,
    assemble_prompt,
    crawl,
)
from lens.core.prompt_transforms import (
    PromptTransformContext,
    PromptTransformTarget,
    transform_prompt,
)
from lens.core.crawl_graph import ComponentSource, CrawlComponent, CrawlTransform
from lens.core.dice import DiceError
from lens.core.exceptions import OperatorError, ValidationError
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import (
    LLMError,
    CommandToolsBundle,
    build_command_tools_bundle,
)
from lens.core.generation_artifacts import GenerationArtifacts, compose_for_operator
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.narrative import NarrativeNode, NodeSegment, parse_segments
from lens.core.operator_params import apply_pinned_invocation
from lens.core.project import ProjectSession, resolve_address
from lens.core.storage import Storage
from lens.core.modalities import (
    InlineGenerationResult,
    ModalityContext,
    PendingInlinePersist,
    ResolvedModalities,
    apply_modality_crawl,
    apply_modality_prompt_addenda,
    merge_modality_command_tools,
    modality_context_from_crawl,
    resolve_modalities,
    apply_modality_post_refine_to_artifacts,
    run_workflow_post_step,
    build_refine_step_defs,
)
from lens.core.workflow_runner import (
    StepResult,
    WorkflowOutcome,
    WorkflowRunner,
    WorkflowStepDef,
    finalize_workflow_outcome,
)

InlineGenerationOutcome = Literal["ok", "interrupted"]

_AT_MENTION_RE = re.compile(
    r"@([a-zA-Z0-9_-]+\.[a-zA-Z0-9_.-]+)(?=\s|$)", re.MULTILINE
)
_AT_NODE_SLICE_RE = re.compile(
    r"@((?:/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*|[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*)@[0-9]+:[0-9]+)(?=\s|$)",
    re.MULTILINE,
)

_log = logging.getLogger(__name__)


def build_feedback_messages(
    previous_content: str, feedback: str, project_root: Path | None
) -> list[dict[str, str]]:
    """Return the two extra message turns for a feedback-guided retry.

    The assistant turn contains the previous output verbatim; the user turn
    is formatted via ``shared.retry_feedback_template`` so it can be
    customised per project/pack like any other prompt.
    """
    from lens.core.prompts import PromptStore

    user_turn = PromptStore(project_root).format(
        "shared.retry_feedback_template", feedback=feedback
    )
    return [
        {"role": "assistant", "content": previous_content},
        {"role": "user", "content": user_turn},
    ]


def extract_annotation_content(md_path: Path, ann: ParsedAnnotation) -> str | None:
    """Return the generated text between an annotation's open and close tags.

    Returns ``None`` if the annotation has no close tag (content not yet
    written or incomplete).  The result is stripped of leading/trailing
    whitespace.
    """
    text = md_path.read_text(encoding="utf-8")
    for seg in parse_segments(text):
        if seg.annotation is None or seg.annotation.line_start != ann.line_start:
            continue
        if seg.close is None:
            return None
        lines = text.split("\n")
        content_lines = lines[ann.line_end : seg.close.line_start - 1]
        return "\n".join(content_lines).strip()
    return None


def _lines_prefix(before_lines: list[str]) -> str:
    """Join lines that precede a splice; empty when *before_lines* is empty.

    Using ``"\\n".join(before) + "\\n"`` would incorrectly insert a leading
    newline when *before* is empty (e.g. mutations starting at line 1).
    """
    if not before_lines:
        return ""
    return "\n".join(before_lines) + "\n"


def _normalize_for_yaml_dump(obj: Any) -> Any:
    """Recursively convert tuples to lists so PyYAML emits portable YAML.

    ``yaml.dump`` uses ``!!python/tuple`` for tuples; ``yaml.safe_load`` in
    annotation parsing cannot reconstruct that tag, which breaks re-parsing
    operator params (e.g. ``luck_rolls`` from advance).
    """
    if isinstance(obj, tuple):
        t = cast(tuple[Any, ...], obj)
        return [_normalize_for_yaml_dump(item) for item in t]
    if isinstance(obj, dict):
        d = cast(dict[Any, Any], obj)
        return {str(k): _normalize_for_yaml_dump(v) for k, v in d.items()}
    if isinstance(obj, list):
        lst = cast(list[Any], obj)
        return [_normalize_for_yaml_dump(item) for item in lst]
    return obj

class Operator(ABC):
    """Base class for all Lens operators.

    Subclasses must set the class variables ``name`` and ``requires_id``,
    and typically override nothing in this class — they compose the helpers
    below in their own domain-specific methods and expose a Typer ``app``
    for CLI registration.
    """

    name: ClassVar[str]
    """Operator name used in annotation tags (e.g. ``"section"``)."""

    requires_id: ClassVar[bool] = True
    """Whether every annotation for this operator must carry an ID."""

    limited_to_datasets: ClassVar[list[str]] = []
    """If non-empty, only available if one of the given datasets is currently active."""

    required_modalities: ClassVar[frozenset[str]] = frozenset()
    """Modality ids always active for this operator (plus default stack)."""

    use_command_tools: ClassVar[bool] = False
    """Whether to expose KB command tools (kb_get, kb_with_tag) to the LLM.

    Operators opt in by setting this to ``True``.  Only planning operators
    (e.g. ``design``) do so; operators that prioritise speed (e.g. ``play``,
    ``write``) keep the default of ``False`` so there is no tool-call overhead.
    """

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def build_instruction(self, params: dict[str, Any]) -> str: ...

    def __init__(self, storage: Storage, narrative_root: NarrativeNode) -> None:
        self.storage = storage
        self.narrative_root = narrative_root

    @property
    def project_root(self) -> Path:
        narrative_root = getattr(self.narrative_root, "narrative_root", None)
        if isinstance(narrative_root, Path):
            return narrative_root.parent.parent
        storage_root = getattr(self.storage, "root", None)
        if isinstance(storage_root, Path):
            return storage_root
        return Path.cwd()

    # ------------------------------------------------------------------
    # Owner address construction
    # ------------------------------------------------------------------

    @classmethod
    def owner_id(
        cls,
        ann_id: str | None,
        file: str,
        line: int | None = None,
    ) -> NarrativeAddress:
        """Build the canonical owner address for this operator.

        Parameters
        ----------
        ann_id:
            The annotation's ID component (the part after the colon in
            ``[section:ch1]``).  ``None`` when the operator does not use
            an ID for this annotation.
        file:
            File path **relative to the git root** where the
            annotation lives (e.g. ``"narrative/test/_node.md"``).
        line:
            1-based line number.  Required when *ann_id* is ``None`` so
            that two ID-less annotations in the same file can be
            distinguished.
        """
        return NarrativeAddress.from_file_and_annotation(
            file, operator=cls.name, op_id=ann_id, line=line
        )

    # ------------------------------------------------------------------
    # Tag builders
    # ------------------------------------------------------------------

    def build_open_tag(
        self,
        id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Return an opening annotation string.

        Examples::

            [section:ch1]: #
            [write
                prompt: hello
            ]: #
        """
        header = f"[{self.name}"
        if id is not None:
            header += f":{id}"
        if not params:
            return f"{header}]: #"
        yaml_text = yaml.dump(
            _normalize_for_yaml_dump(params),
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip("\n")
        indented = re.sub(r"^", "    ", yaml_text, flags=re.MULTILINE)
        return f"{header}\n{indented}\n]: #"

    def build_close_tag(self, id: str | None = None) -> str:
        """Return a closing annotation string, e.g. ``[/section:ch1]: #``."""
        tag = f"[/{self.name}"
        if id is not None:
            tag += f":{id}"
        return f"{tag}]: #"

    def build_self_closing_tag(self, id: str | None = None) -> str:
        """Return a self-closing annotation, e.g. ``[chat:reflect/]: #``."""
        tag = f"[{self.name}"
        if id is not None:
            tag += f":{id}"
        return f"{tag}/]: #"

    # ------------------------------------------------------------------
    # Annotation reading helpers (normal Path reads, no Storage needed)
    # ------------------------------------------------------------------

    def find_my_annotations(self, text: str) -> list[ParsedAnnotation]:
        """Return all annotations in *text* that belong to this operator."""
        return [a for a in parse_annotations(text) if a.operator == self.name]

    def find_my_segments(self, text: str) -> list[NodeSegment]:
        """Return segments owned by this operator (annotation matches name)."""
        return [
            s for s in parse_segments(text)
            if s.annotation is not None and s.annotation.operator == self.name
        ]

    # ------------------------------------------------------------------
    # Node write helpers (via Storage)
    # ------------------------------------------------------------------

    def append_to_node(self, node: NarrativeNode, text: str) -> None:
        """Append *text* to the node's markdown file via Storage.

        Ensures a blank-line separator before the appended text when the
        file doesn't already end with one.
        """
        md = node.md_path()
        current = md.read_text(encoding="utf-8")
        sep = "\n" if current.endswith("\n") else "\n\n"
        self.storage.write_file(md, current + sep + text)

    def _relative_path(self, absolute: Path) -> str:
        """Return *absolute* as a path relative to the storage root."""
        return str(absolute.relative_to(self.storage.root))

    # ------------------------------------------------------------------
    # Mode 2 helpers — sub-node creation / closing
    # ------------------------------------------------------------------

    def create_subnode(
        self,
        parent: NarrativeNode,
        id: str,
        initial_content: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> NarrativeNode:
        """Create a leaf child node and append an open tag to *parent*.

        The child is created as a leaf (``{id}.md``). It can be converted
        to a folder later via :meth:`~lens.narrative.NarrativeNode.to_folder`
        if needed. If *parent* is a leaf, it is promoted to a folder first
        (required by the path model for children to exist).
        """
        if parent.is_leaf():
            parent.to_folder(self.storage)

        md_path = parent.md_path()
        child_md = md_path.parent / f"{id}.md"
        self.storage.write_file(child_md, initial_content or "")

        tag = self.build_open_tag(id, params)
        self.append_to_node(parent, tag + "\n")

        return parent.child_node(id)

    def close_subnode(
        self,
        parent: NarrativeNode,
        id: str,
        summary: str = "",
    ) -> None:
        """Close a sub-node by appending *summary* and a close tag to *parent*.

        *summary* is appended **as-is** — callers that produce an LLM summary
        must pre-format it using
        :func:`lens.core.operators.session.format_summary_block` (or
        :func:`lens.core.operators.session.generate_summary_block`) so that
        every summary in the tree has the canonical ``<!-- section:<slug> -->``
        + ``###`` title + one continuous blockquoted body. Raw text that does
        not satisfy the title rule raises ``SummaryTitleError`` from
        ``lens.core.operators.session``.
        """
        close = self.build_close_tag(id)
        if summary:
            suffix = summary.rstrip("\n") + "\n\n" + close + "\n"
        else:
            suffix = close + "\n"
        self.append_to_node(parent, suffix)

    # ------------------------------------------------------------------
    # Mode 1 helpers — inline content (same-node open/close)
    # ------------------------------------------------------------------

    def write_inline(
        self,
        node: NarrativeNode,
        id: str | None,
        content: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Single-step inline: open tag + content + close tag in one write."""
        open_tag = self.build_open_tag(id, params)
        close_tag = self.build_close_tag(id)
        block = f"{open_tag}\n\n{content}\n\n{close_tag}\n"
        self.append_to_node(node, block)

    def open_inline(
        self,
        node: NarrativeNode,
        id: str | None,
        params: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError("open_inline is removed (steps are no longer supported)")

    def continue_inline(
        self,
        node: NarrativeNode,
        id: str | None,
        content: str,
    ) -> None:
        raise NotImplementedError("continue_inline is removed (steps are no longer supported)")

    def close_inline(self, node: NarrativeNode, id: str | None) -> None:
        """Append a close tag for the open inline block."""
        close_tag = self.build_close_tag(id)
        self.append_to_node(node, close_tag + "\n")

    # ------------------------------------------------------------------
    # Mode 3 helpers — mutation (claim / propose / cancel)
    # ------------------------------------------------------------------

    def start_mutation(
        self,
        file_path: Path,
        start_line: int,
        end_line: int,
        id: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Wrap lines *start_line*..*end_line* (1-based, inclusive) in claim
        tags, then force-stage so the claim is committed to the index.

        *params* are stored in the open claim tag so they can be recovered
        on retry without the caller re-supplying them.

        After this call a new pending transaction can be opened with
        :meth:`propose_mutation`.
        """
        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        before = lines[: start_line - 1]
        claimed = lines[start_line - 1 : end_line]
        after = lines[end_line:]
        open_tag = self.build_open_tag(id, params)
        close_tag = self.build_close_tag(id)
        rebuilt = (
            _lines_prefix(before)
            + open_tag
            + "\n"
            + "\n".join(claimed)
            + "\n\n"
            + close_tag
            + "\n"
            + "\n".join(after)
        )
        self.storage.write_file(file_path, rebuilt)
        self.storage.stage_all()

    def propose_mutation(
        self,
        file_path: Path,
        id: str,
        new_content: str,
    ) -> None:
        """Replace the claimed region (including claim tags) with
        *new_content*.  The result is an unstaged transaction that removes
        the claim tags and substitutes the original text."""
        text = file_path.read_text(encoding="utf-8")
        anns = self.find_my_annotations(text)
        open_ann: ParsedAnnotation | None = None
        close_ann: ParsedAnnotation | None = None
        for a in anns:
            if a.id != id:
                continue
            if not a.closing and not a.self_closing:
                open_ann = a
            elif a.closing:
                close_ann = a
        if open_ann is None or close_ann is None:
            raise ValueError(
                f"Claim [{self.name}:{id}] not found in {file_path}"
            )
        lines = text.split("\n")
        before = lines[: open_ann.line_start - 1]
        after = lines[close_ann.line_end :]
        if new_content == "":
            rebuilt = _lines_prefix(before) + "\n".join(after)
        else:
            rebuilt = (
                _lines_prefix(before)
                + new_content
                + "\n"
                + "\n".join(after)
            )
        self.storage.write_file(file_path, rebuilt)

    def cancel_mutation(
        self,
        file_path: Path,
        id: str,
    ) -> None:
        """Remove claim tags but keep the original text, then stage.

        This is the compensating transaction for :meth:`start_mutation`.
        """
        text = file_path.read_text(encoding="utf-8")
        anns = self.find_my_annotations(text)
        open_ann: ParsedAnnotation | None = None
        close_ann: ParsedAnnotation | None = None
        for a in anns:
            if a.id != id:
                continue
            if not a.closing and not a.self_closing:
                open_ann = a
            elif a.closing:
                close_ann = a
        if open_ann is None or close_ann is None:
            raise ValueError(
                f"Claim [{self.name}:{id}] not found in {file_path}"
            )
        lines = text.split("\n")
        before = lines[: open_ann.line_start - 1]
        claimed = lines[open_ann.line_end : close_ann.line_start - 1]
        after = lines[close_ann.line_end :]
        rebuilt = (
            _lines_prefix(before)
            + "\n".join(claimed)
            + "\n"
            + "\n".join(after)
        )
        self.storage.write_file(file_path, rebuilt)
        self.storage.stage_all()

    # ------------------------------------------------------------------
    # LLM / context-aware static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def ann_line_for_append(text: str) -> int:
        """1-based line where a newly appended annotation will appear.

        Mirrors the separator logic in ``append_to_node``: one blank line
        if the file already ends with a newline, two otherwise.
        """
        n = len(text.split("\n"))
        return n + (1 if text.endswith("\n") else 2)

    @staticmethod
    def extract_list(params: dict[str, Any], key: str) -> list[str]:
        raw = params.get(key)
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(item, str):
                result.append(item)
        return result

    @staticmethod
    def merge_extra_pin_ids(*parts: list[str]) -> list[str]:
        """Concatenate pin id lists, deduplicating while preserving first-seen order."""
        out: list[str] = []
        seen: set[str] = set()
        for part in parts:
            for cid in part:
                if cid in seen:
                    continue
                seen.add(cid)
                out.append(cid)
        return out

    @staticmethod
    def attach_prompt_component(crawl_result: CrawlResult, prompt: str | None) -> None:
        """Let graph transforms inspect a prompt without rendering it verbatim."""

        if not prompt:
            return
        crawl_result.graph.add_component(
            CrawlComponent(
                id=crawl_result.graph.next_id("operator-prompt"),
                kind="metadata",
                text=prompt,
                role="none",
                source=ComponentSource(kind="prompt", identifier="operator_prompt"),
                visibility={"hidden"},
            )
        )

    @classmethod
    def _inline_command_tools_bundle(
        cls,
        project_root: Path,
        ann_params: dict[str, Any],
    ) -> CommandToolsBundle | None:
        """Optional per-operator command tools for inline / retry generation.

        When non-``None``, overrides :attr:`use_command_tools` full registry.
        """
        del project_root, ann_params
        return None

    @staticmethod
    def mention_pins(prompt: str | None, project_root: Path) -> list[str]:
        """Return KB IDs found as ``@type.key`` mentions in *prompt* that exist.

        Only IDs that can be resolved in the knowledge store are returned.
        Duplicates are deduplicated while preserving first-occurrence order.
        """
        if not prompt:
            return []
        kb_store = KnowledgeStore.for_project(project_root)
        found: list[str] = []
        seen: set[str] = set()
        for m in _AT_MENTION_RE.finditer(prompt):
            cid = m.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            if kb_store.exists(cid):
                found.append(cid)
        return found

    @classmethod
    def transform_storable_prompt(
        cls,
        text: str,
        *,
        session: ProjectSession,
        cursor: NarrativeNode,
    ) -> str:
        """Storable pre-pass: vars, inline-tag KB, rolls, ``@now`` before crawl/storage."""
        del cls
        return transform_prompt(
            text,
            PromptTransformContext(
                project_root=session.project_root,
                storage=session.new_storage(),
                cursor=cursor,
            ),
            target=PromptTransformTarget.STORABLE,
        )

    @staticmethod
    def _format_node_slice_ref(
        addr: NarrativeAddress, project_root: Path
    ) -> str | None:
        if addr.cursor or addr.line is None or addr.line_end is None:
            return None
        if addr.line < 1 or addr.line_end < addr.line:
            return None
        try:
            resolved = resolve_address(addr, project_root)
        except ValueError:
            return None
        if (
            resolved.cursor
            or resolved.narrative is None
            or resolved.line is None
            or resolved.line_end is None
        ):
            return None
        node = resolved.to_node(project_root)
        if not node.exists():
            return None
        lines = node.md_path().read_text(encoding="utf-8").split("\n")
        if resolved.line_end > len(lines):
            return None
        excerpt = "\n".join(lines[resolved.line - 1 : resolved.line_end]).rstrip()
        if not excerpt:
            return None
        # Emit the excerpt verbatim (no indentation/wrapping) so line-based
        # content tools can echo back a body line exactly as the LLM sees it.
        return f"REF[{str(resolved)!r}]\n{excerpt}\n"

    @classmethod
    def mention_node_slice_refs(
        cls, prompt: str | None, project_root: Path
    ) -> list[str]:
        """Return formatted node slice refs found as ``@/path@start:end`` mentions."""
        if not prompt:
            return []
        refs: list[str] = []
        for m in _AT_NODE_SLICE_RE.finditer(prompt):
            raw = m.group(1)
            try:
                addr = NarrativeAddress.parse(raw)
            except ValueError:
                continue
            formatted = cls._format_node_slice_ref(addr, project_root)
            if formatted is not None:
                refs.append(formatted)
        return refs

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        """Override to raise :class:`OperatorError` if prerequisites are not met.

        Called immediately after :func:`~lens.core.context.crawl` in fresh
        inline generation.  Inspect ``crawl_result.pinned_ids`` for the
        canonical effective pin list (ancestor hierarchy already resolved).
        The default implementation imposes no requirements.
        """

    @staticmethod
    async def stream_output(
        messages: list[dict[str, str]],
        project_root: Path,
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        *,
        operator_name: str | None = None,
        reasoning: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        command_tool_handlers: dict[str, CommandToolFn] | None = None,
    ) -> GenerationArtifacts:
        """Stream LLM output and return structured generation artifacts."""
        return await run_llm(
            LlmRunRequest(
                project_root=project_root,
                messages=messages,
                llm_id=llm_id,
                tools=tools,
                command_tool_handlers=command_tool_handlers,
                cancel_event=cancel_event,
                on_token=on_token,
                operator_name=operator_name,
                reasoning=reasoning,
            ),
        )

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    def find_open_annotation(self, node: NarrativeNode) -> ParsedAnnotation | None:
        """Return the last annotation for this operator in the node file.

        Pending state is tracked by git (unstaged changes), not by whether the
        annotation has a close tag, so this returns the last matching annotation
        regardless of whether it is open or closed.
        """
        text = node.md_path().read_text(encoding="utf-8")
        segments = parse_segments(text)
        for seg in reversed(segments):
            if seg.annotation is None:
                continue
            if seg.annotation.operator != self.name:
                continue
            return seg.annotation
        return None

    def content_prefix_for_fresh(self, params: dict[str, Any]) -> str:
        """Optional text to write before the LLM output when starting a fresh inline run.

        Override in subclasses (e.g. play) to persist the user prompt in the narrative.
        """
        return ""

    @classmethod
    def enrich_params(cls, crawl_result: CrawlResult, params: dict[str, Any]) -> None:
        """Optional hook to fill params from crawl result (e.g. play sets pc_key from pinned PCs)."""
        return None

    @classmethod
    async def _run_post_inline_hooks(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        on_status: Callable[[str], None] | None = None,
        on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Run registered post-inline-generation hooks (e.g. auto-compress).

        Called from :meth:`run_inline` and from session operator
        ``_run_inside`` / ``_run_fresh`` paths that bypass ``run_inline``.
        """
        if cls.name not in ("write", "play", "chat"):
            return
        from lens.core.hooks import HookContext, run_hooks

        ctx = HookContext(
            session=session,
            narrative=narrative,
            cursor=cursor,
            operator_name=cls.name,
            trigger="post_inline",
            on_token=on_token,
            cancel_event=cancel_event,
            on_status=on_status,
            on_info_event=on_info_event,
        )
        await run_hooks(ctx)

    def write_start(
        self,
        node: NarrativeNode,
        tag: str,
        content: str = "",
        *,
        verbatim_prefix: str = "",
        artifacts: GenerationArtifacts | None = None,
    ) -> None:
        """Atomically write an open tag, generated content, and close tag to the node.

        Pass *artifacts* from :func:`~lens.core.llm_run.run_llm` (composed per
        operator policy) or plain *content* string. *verbatim_prefix* is
        user-authored text prepended unchanged (e.g. chat scene).
        """
        if artifacts is not None:
            content = compose_for_operator(artifacts, self.__class__.name)
        body = verbatim_prefix + content if verbatim_prefix else content
        md = node.md_path()
        current = md.read_text(encoding="utf-8") if md.exists() else ""
        sep = "\n" if current.endswith("\n") else "\n\n"
        close_tag = self.build_close_tag(None)
        self.storage.write_file(
            md, current + sep + tag + "\n\n" + body.rstrip() + "\n\n" + close_tag + "\n"
        )

    def write_append(
        self,
        node: NarrativeNode,
        ann: ParsedAnnotation,
        new_content: str = "",
        *,
        verbatim_prefix: str = "",
        artifacts: GenerationArtifacts | None = None,
    ) -> None:
        """Preserve existing content, append new content before close tag."""
        if artifacts is not None:
            new_content = compose_for_operator(artifacts, self.__class__.name)
        new_content = verbatim_prefix + new_content if verbatim_prefix else new_content
        md = node.md_path()
        text = md.read_text(encoding="utf-8")
        new_tag = self.build_open_tag(ann.id, dict(ann.params) or None)
        close_tag = self.build_close_tag(ann.id)

        close_ann: ParsedAnnotation | None = None
        for seg in parse_segments(text):
            if seg.annotation is not None and seg.annotation.line_start == ann.line_start:
                close_ann = seg.close
                break

        lines = text.split("\n")
        before = lines[: ann.line_start - 1]

        if close_ann is not None:
            content_lines = lines[ann.line_end : close_ann.line_start - 1]
            after_close = lines[close_ann.line_end :]
            rebuilt = (
                "\n".join(before)
                + "\n"
                + new_tag
                + "\n"
                + "\n".join(content_lines)
                + "\n"
                + new_content.rstrip()
                + "\n\n"
                + close_tag
                + "\n"
                + ("\n".join(after_close) if after_close else "")
            )
        else:
            after_tag = lines[ann.line_end :]
            rebuilt = (
                "\n".join(before)
                + "\n"
                + new_tag
                + "\n"
                + "\n".join(after_tag)
                + "\n"
                + new_content.rstrip()
                + "\n\n"
                + close_tag
                + "\n"
            )
        self.storage.write_file(md, rebuilt)

    def write_discard(
        self,
        node: NarrativeNode,
        ann: ParsedAnnotation,
        updated_params: dict[str, Any] | None = None,
    ) -> None:
        """Remove generated content, optionally update params."""
        md = node.md_path()
        text = md.read_text(encoding="utf-8")
        params = dict(updated_params if updated_params is not None else ann.params)
        new_tag = self.build_open_tag(ann.id, params or None)
        lines = text.split("\n")
        before = lines[: ann.line_start - 1]
        rebuilt = "\n".join(before) + "\n" + new_tag + "\n"
        self.storage.write_file(md, rebuilt)

    def extra_crawl_transforms(
        self, crawl_result: CrawlResult, params: dict[str, Any]
    ) -> list[CrawlTransform]:
        return []

    @classmethod
    def participants_for_crawl(cls, params: dict[str, Any]) -> dict[str, str]:
        """Operator-specific participants to set on :class:`CrawlSpec`.

        Default is empty.  Override in subclasses (e.g. ``chat``) to map
        annotation params like ``as_kb_id`` / ``with_kb_id`` onto graph
        participants without rebuilding ``extra_crawl_transforms``.
        """
        del params
        return {}

    @classmethod
    def modules_for_crawl(cls, node: NarrativeNode) -> tuple[str, ...]:
        """Operator-specific modules to set on :class:`CrawlSpec`.

        Default is empty.  Session operators override this to derive the
        active session module (canonical KB id) from the parent open
        annotation so :class:`ModuleTransform` resolves it at crawl time.
        """
        del node
        return ()

    @classmethod
    def extra_required_modalities(cls, params: dict[str, Any]) -> frozenset[str]:
        del params
        return frozenset()

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
        """Build a :class:`~lens.core.context.CrawlSpec` that merges modalities in :func:`~lens.core.context.crawl`.

        When ``modules`` is omitted, fills it from :meth:`modules_for_crawl` (session
        operators resolve the parent annotation's ``module:`` param).
        """
        if "modules" not in kwargs:
            derived = cls.modules_for_crawl(node)
            if derived:
                kwargs = {**kwargs, "modules": derived}
        return CrawlSpec.of(
            node,
            operator=cls,
            operator_params=params,
            session=session,
            narrative=narrative,
            **kwargs,
        )

    @classmethod
    def crawl_with_modalities(
        cls,
        spec: CrawlSpec,
        params: dict[str, Any],
        *,
        session: ProjectSession | None,
        narrative: NarrativeNode,
    ) -> tuple[CrawlResult, ModalityContext, ResolvedModalities]:
        """Run :func:`~lens.core.context.crawl` and return modality context for the same run."""
        enriched = spec.with_operator(cls, params, session=session, narrative=narrative)
        crawl_result = crawl(enriched)
        ctx, resolved = modality_context_from_crawl(enriched, crawl_result)
        return crawl_result, ctx, resolved

    @classmethod
    def merge_command_tools_for_generation(
        cls,
        resolved: ResolvedModalities,
        ctx: ModalityContext,
        project_root: Path,
        params: dict[str, Any],
    ) -> tuple[list[dict[str, Any]] | None, dict[str, CommandToolFn] | None]:
        """Operator command tools plus active modality tools."""
        tools_payload: list[dict[str, Any]] | None = None
        command_handlers: dict[str, CommandToolFn] | None = None
        override = cls._inline_command_tools_bundle(project_root, params)
        if override is not None:
            tools_payload = override.tools
            command_handlers = override.handlers
        elif cls.use_command_tools:
            bundle = build_command_tools_bundle(project_root)
            tools_payload = bundle.tools
            command_handlers = bundle.handlers
        return merge_modality_command_tools(
            tools_payload, command_handlers, resolved, ctx
        )

    @classmethod
    async def apply_modality_post_refine(
        cls,
        session: ProjectSession,
        artifacts: GenerationArtifacts,
        *,
        resolved: ResolvedModalities,
        ctx: ModalityContext,
        workflow: Any | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> tuple[GenerationArtifacts, tuple[str, ...]]:
        """Post-process and optionally refine composed prose before persist."""
        out, warns = await apply_modality_post_refine_to_artifacts(
            session,
            artifacts,
            cls.name,
            resolved,
            ctx,
            workflow=workflow,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        if workflow is None and warns:
            for line in warns:
                _log.warning("%s", line)
                print(line, file=sys.stderr)
        return out, warns

    def _modality_context(
        self,
        crawl_result: CrawlResult,
        params: dict[str, Any],
        *,
        session: ProjectSession | None = None,
        narrative: NarrativeNode | None = None,
    ) -> tuple[ModalityContext, ResolvedModalities]:
        cached = crawl_result.modality_resolution
        base_ctx = crawl_result.modality_context
        if cached is not None and base_ctx is not None:
            from dataclasses import replace as dc_replace

            nar = narrative if narrative is not None else base_ctx.narrative
            ctx = dc_replace(
                base_ctx,
                crawl_result=crawl_result,
                params=dict(params),
                session=session if session is not None else base_ctx.session,
                narrative=nar,
            )
            return ctx, cached

        focus = crawl_result.current_node or self.narrative_root
        root = crawl_result.project_root
        if root is None:
            root = self.storage.root
        nar = narrative if narrative is not None else self.narrative_root
        ctx = ModalityContext(
            session=session,
            narrative=nar,
            focus_node=focus,
            operator_name=self.name,
            crawl_result=crawl_result,
            params=params,
            project_root=root,
        )
        resolved, prepared_ctx = resolve_modalities(
            type(self), focus, params=params, ctx=ctx
        )
        return prepared_ctx, resolved

    def build_messages(
        self,
        crawl_result: CrawlResult,
        params: dict[str, Any],
        *,
        session: ProjectSession | None = None,
        narrative: NarrativeNode | None = None,
        resolved_modalities: Any | None = None,
    ) -> list[dict[str, str]]:
        from lens.core.turns import parse_passage_turns

        apply_transforms_to_result(
            crawl_result, self.extra_crawl_transforms(crawl_result, params)
        )
        ctx, resolved = self._modality_context(
            crawl_result, params, session=session, narrative=narrative
        )
        if resolved_modalities is not None:
            resolved = resolved_modalities
        apply_modality_crawl(crawl_result, resolved, ctx)
        instruction = self.build_instruction(params)
        turns: list[tuple[str, str]] | None = None
        node = crawl_result.current_node
        if node is not None:
            result = parse_passage_turns(self.storage.normalize_path_text(node.md_path()))
            if result:
                turns = result
        messages = assemble_prompt(
            crawl_result,
            system_prompt=self.system_prompt,
            instruction=instruction,
            turns=turns,
        )
        return apply_modality_prompt_addenda(messages, resolved, ctx)

    @classmethod
    def _owner_for_ann(cls, ann: ParsedAnnotation, rel_path: str) -> NarrativeAddress:
        line = ann.line_start if ann.id is None else None
        return cls.owner_id(ann.id, rel_path, line=line)

    # ------------------------------------------------------------------
    # Inline flow orchestrator (write, play, …)
    # ------------------------------------------------------------------

    @classmethod
    async def run_inline(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        on_status: Callable[[str], None] | None = None,
        on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        _cursor_override: NarrativeNode | None = None,
        empty_prompt_ok: bool = False,
        workflow: WorkflowRunner | None = None,
    ) -> WorkflowOutcome | None:
        """Run the inline flow (fresh / retry / update-retry).

        *empty_prompt_ok* is for operators (e.g. play) that persist the user
        turn outside the annotation and call the LLM with instruction-only
        context; they pass ``prompt=None`` into this orchestrator.

        Returns :class:`WorkflowOutcome` when a multi-step workflow ran (write/play/chat).

        Raises :class:`OperatorError` on user-visible failures.
        """
        cursor = _cursor_override if _cursor_override is not None else narrative.find_cursor()

        llm_id, reasoning, merged_extra = apply_pinned_invocation(
            slug=cls.name,
            project_root=session.project_root,
            focus_node=cursor,
            narrative=narrative,
            llm_id=llm_id,
            reasoning=reasoning,
            extra_params=extra_params,
        )
        extra_params = merged_extra if merged_extra else None

        if prompt:
            try:
                prompt = cls.transform_storable_prompt(
                    prompt, session=session, cursor=cursor
                )
            except DiceError as e:
                raise ValidationError(str(e)) from e

        mention_pins = cls.mention_pins(prompt, session.project_root)
        if mention_pins:
            pins = pins + mention_pins

        async def run_generate() -> StepResult:
            gen = await cls._run_inline_generation(
                session=session,
                narrative=narrative,
                cursor=cursor,
                prompt=prompt,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                reasoning=reasoning,
                retry=retry,
                extra_params=extra_params,
                on_token=on_token,
                cancel_event=cancel_event,
                empty_prompt_ok=empty_prompt_ok,
            )
            if gen.outcome == "interrupted":
                runner.clear_inline_modality_state()
                return StepResult(ok=False, cancelled=True)
            if gen.pending is not None:
                from lens.core.modalities.workflow import (
                    cache_refine_modality_ids_on_pending,
                )

                if gen.resolved is not None and gen.modality_context is not None:
                    cache_refine_modality_ids_on_pending(
                        gen.pending, gen.resolved, gen.modality_context
                    )
                runner.set_inline_modality_state(
                    pending=gen.pending,
                    resolved=gen.resolved,
                    modality_context=gen.modality_context,
                )
            return StepResult(ok=True)

        def workflow_post_should_run() -> bool:
            from lens.core.modalities.workflow import modality_workflow_post_needed

            resolved = runner.resolved_modalities
            if resolved is None:
                return False
            return modality_workflow_post_needed(resolved)

        async def run_workflow_post() -> StepResult:
            return await run_workflow_post_step(
                pending=runner.pending_inline,
                resolved=runner.resolved_modalities,
                ctx=runner.modality_context,
            )

        def persist_should_run() -> bool:
            return runner.pending_inline is not None

        async def run_persist() -> StepResult:
            pending = runner.pending_inline
            if pending is None:
                return StepResult(ok=True, skipped=True)
            storage = session.new_storage(owner=pending.owner)
            op = cls(storage, pending.narrative)
            if pending.mode == "start":
                op.write_start(
                    pending.cursor,
                    pending.tag,
                    artifacts=pending.artifacts,
                    verbatim_prefix=pending.verbatim_prefix,
                )
            else:
                assert pending.existing_ann is not None
                op.write_append(
                    pending.cursor,
                    pending.existing_ann,
                    artifacts=pending.artifacts,
                    verbatim_prefix=pending.verbatim_prefix,
                )
            runner.clear_inline_modality_state()
            return StepResult(ok=True)

        async def run_auto_compress() -> StepResult:
            if cls.name not in ("write", "play", "chat"):
                return StepResult(ok=True, skipped=True)
            from lens.core.auto_compress import run_auto_compress_workflow_step

            return await run_auto_compress_workflow_step(
                session,
                narrative,
                on_token=on_token,
                cancel_event=cancel_event,
                on_status=on_status,
                on_info_event=on_info_event,
                workflow=runner,
            )

        def auto_compress_should_run() -> bool:
            if cls.name not in ("write", "play", "chat"):
                return False
            from lens.core.auto_compress import read_cursor_auto_compress_state

            state = read_cursor_auto_compress_state(session, narrative)
            return bool(state.compress_on and state.trigger is not None)

        runner = workflow or WorkflowRunner(
            session=session,
            cancel_event=cancel_event,
            on_status=on_status,
        )
        steps = [
            WorkflowStepDef(
                id="generate",
                label=f"Generating ({cls.name})…",
                run=run_generate,
                failure_policy="fatal",
            ),
            WorkflowStepDef(
                id="workflow_post",
                label="Post-processing…",
                run=run_workflow_post,
                should_run=workflow_post_should_run,
                failure_policy="warn",
                skippable=True,
            ),
            *build_refine_step_defs(
                session,
                get_pending=lambda: runner.pending_inline,
                get_resolved=lambda: runner.resolved_modalities,
                get_ctx=lambda: runner.modality_context,
                on_token=on_token,
                cancel_event=cancel_event,
            ),
            WorkflowStepDef(
                id="persist",
                label="Saving…",
                run=run_persist,
                should_run=persist_should_run,
                failure_policy="fatal",
            ),
            WorkflowStepDef(
                id="auto_compress",
                label="Auto-compressing…",
                run=run_auto_compress,
                should_run=auto_compress_should_run,
                failure_policy="warn",
                skippable=True,
                abort_rolls_back=True,
            ),
        ]
        outcome = await runner.run(steps)
        return finalize_workflow_outcome(session, outcome)

    @classmethod
    async def _run_inline_generation(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        prompt: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        reasoning: str | None,
        retry: bool,
        extra_params: dict[str, Any] | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
        empty_prompt_ok: bool,
    ) -> InlineGenerationResult:
        cursor_md = cursor.md_path()
        rel_path = str(cursor_md.relative_to(session.git_root))

        probe_storage = session.new_storage()
        has_pending = probe_storage.has_pending()
        pending_owner = probe_storage.detect_pending_owner() if has_pending else None

        probe_op = cls(probe_storage, narrative)
        existing_ann = probe_op.find_open_annotation(cursor)

        is_owner = False
        if existing_ann is not None and pending_owner is not None:
            is_owner = pending_owner == cls._owner_for_ann(existing_ann, rel_path)

        if retry and not is_owner:
            raise ValidationError(f"no pending {cls.name} transaction to retry")

        if is_owner:
            assert existing_ann is not None
            if retry:
                return await cls._do_retry(
                    session, narrative, cursor, rel_path, existing_ann,
                    prompt=prompt, pins=pins or [], unpins=unpins or [],
                    llm_id=llm_id, reasoning=reasoning, extra_params=extra_params,
                    on_token=on_token, cancel_event=cancel_event,
                )
            elif prompt or pins or unpins or (
                llm_id and llm_id != existing_ann.params.get("llm_id")
            ) or (
                reasoning and reasoning != existing_ann.params.get("reasoning")
            ):
                session.new_storage().stage_all()
                print(f"Committed pending {cls.name}. Starting fresh.", file=sys.stderr)
                return await cls._do_fresh_inline(
                    session, narrative, cursor, rel_path,
                    prompt, pins, unpins, llm_id,
                    reasoning=reasoning,
                    on_token=on_token,
                    extra_params=extra_params,
                    cancel_event=cancel_event,
                )
            else:
                if not prompt and not empty_prompt_ok:
                    raise ValidationError(f"{cls.name} requires a prompt (or --retry)")
                session.new_storage().stage_all()
                return await cls._do_fresh_inline(
                    session, narrative, cursor, rel_path,
                    prompt, pins, unpins, llm_id,
                    reasoning=reasoning,
                    on_token=on_token,
                    extra_params=extra_params,
                    cancel_event=cancel_event,
                )
        else:
            if has_pending:
                session.new_storage().stage_all()
            return await cls._do_fresh_inline(
                session, narrative, cursor, rel_path,
                prompt, pins, unpins, llm_id,
                reasoning=reasoning,
                on_token=on_token,
                extra_params=extra_params,
                cancel_event=cancel_event,
            )

    @classmethod
    async def _do_fresh_inline(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        rel_path: str,
        prompt: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        reasoning: str | None = None,
    ) -> InlineGenerationResult:
        ann_params: dict[str, Any] = {}
        if prompt:
            ann_params["prompt"] = prompt
        if pins:
            ann_params["kb_pin"] = pins
        if unpins:
            ann_params["kb_unpin"] = unpins
        if llm_id:
            ann_params["llm_id"] = llm_id
        if reasoning:
            ann_params["reasoning"] = reasoning
        if extra_params:
            ann_params.update(extra_params)

        current_text = cursor.md_path().read_text(encoding="utf-8")
        ann_line = cls.ann_line_for_append(current_text)
        owner = cls.owner_id(None, rel_path, line=ann_line)

        mention_ids = cls.mention_pins(prompt, session.project_root)
        if mention_ids:
            existing_pins = cls.extract_list(ann_params, "kb_pin")
            ann_params["kb_pin"] = existing_pins + mention_ids
        with_id = ann_params.get("with_kb_id")
        with_extra = (
            [str(with_id).strip()]
            if isinstance(with_id, str) and str(with_id).strip()
            else []
        )
        crawl_storage = session.new_storage()
        crawl_result, ctx, resolved = cls.crawl_with_modalities(
            cls.crawl_spec(
                cursor,
                ann_params,
                session=session,
                narrative=narrative,
                extra_pins=cls.merge_extra_pin_ids(
                    list(pins), list(mention_ids), with_extra
                ),
                extra_unpins=unpins,
                storage=crawl_storage,
                participants=cls.participants_for_crawl(ann_params),
            ),
            ann_params,
            session=session,
            narrative=narrative,
        )
        cls.attach_prompt_component(crawl_result, prompt)
        cls.check_requirements(crawl_result)
        cls.enrich_params(crawl_result, ann_params)

        probe_op = cls(crawl_storage, narrative)
        tag = probe_op.build_open_tag(None, ann_params)

        artifacts = GenerationArtifacts()

        tools_payload, command_handlers = cls.merge_command_tools_for_generation(
            resolved, ctx, session.project_root, ann_params
        )

        try:
            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    crawl_result=crawl_result,
                    operator=probe_op,
                    params=ann_params,
                    llm_id=llm_id,
                    reasoning=reasoning,
                    operator_name=cls.name,
                    tools=tools_payload,
                    command_tool_handlers=command_handlers,
                    resolved_modalities=resolved,
                    modality_context=ctx,
                    on_token=on_token,
                    cancel_event=cancel_event,
                ),
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted:
            return InlineGenerationResult(outcome="interrupted")

        if not artifacts.has_content():
            raise OperatorError("no content generated")

        pending = PendingInlinePersist(
            mode="start",
            cursor=cursor,
            tag=tag,
            artifacts=artifacts,
            verbatim_prefix=probe_op.content_prefix_for_fresh(ann_params),
            existing_ann=None,
            owner=owner,
            narrative=narrative,
            operator_name=cls.name,
        )
        return InlineGenerationResult(
            outcome="ok",
            pending=pending,
            resolved=resolved,
            modality_context=ctx,
        )

    @classmethod
    async def _do_continue(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        rel_path: str,
        existing_ann: ParsedAnnotation,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        ann_pins = cls.extract_list(existing_ann.params, "kb_pin")
        ann_unpins = cls.extract_list(existing_ann.params, "kb_unpin")
        ann_llm_id: str | None = existing_ann.params.get("llm_id")
        ann_reasoning: str | None = existing_ann.params.get("reasoning")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)

        with_id = existing_ann.params.get("with_kb_id")
        with_extra = (
            [str(with_id).strip()]
            if isinstance(with_id, str) and str(with_id).strip()
            else []
        )
        ann_dict = dict(existing_ann.params)
        crawl_result, ctx, resolved = cls.crawl_with_modalities(
            cls.crawl_spec(
                cursor,
                ann_dict,
                session=session,
                narrative=narrative,
                extra_pins=cls.merge_extra_pin_ids(ann_pins, with_extra),
                extra_unpins=ann_unpins,
                storage=op.storage,
                participants=cls.participants_for_crawl(ann_dict),
            ),
            ann_dict,
            session=session,
            narrative=narrative,
        )
        cls.enrich_params(crawl_result, existing_ann.params)
        messages = op.build_messages(
            crawl_result,
            ann_dict,
            session=session,
            narrative=narrative,
            resolved_modalities=resolved,
        )
        cont_tools, cont_handlers = cls.merge_command_tools_for_generation(
            resolved, ctx, session.project_root, ann_dict
        )

        try:
            artifacts = await cls.stream_output(
                messages,
                session.project_root,
                ann_llm_id,
                on_token,
                cancel_event=cancel_event,
                operator_name=cls.name,
                reasoning=ann_reasoning,
                tools=cont_tools,
                command_tool_handlers=cont_handlers,
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted:
            return

        if not artifacts.has_content():
            raise OperatorError("no content generated")

        artifacts, _refine_warnings = await cls.apply_modality_post_refine(
            session,
            artifacts,
            resolved=resolved,
            ctx=ctx,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        op.write_append(cursor, existing_ann, artifacts=artifacts)
        print(f"Continued writing in {cursor.path_str()}", file=sys.stderr)

    @classmethod
    async def _do_retry(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        rel_path: str,
        existing_ann: ParsedAnnotation,
        prompt: str | None = None,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
        llm_id: str | None = None,
        reasoning: str | None = None,
        extra_params: dict[str, Any] | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> InlineGenerationResult:
        # When a prompt is supplied on --retry, treat it as feedback rather than
        # a replacement for the stored prompt.  We capture the previous generated
        # content, keep the original annotation params intact, and append two
        # extra turns before re-generating:
        #   • assistant: previous output
        #   • user:      feedback
        feedback = prompt
        previous_content: str | None = None
        if feedback:
            previous_content = extract_annotation_content(cursor.md_path(), existing_ann)

        new_params: dict[str, Any] = dict(existing_ann.params)
        # Do NOT overwrite the stored prompt — feedback is a separate message
        # turn, not a new annotation param.
        if pins:
            new_params["kb_pin"] = pins
        if unpins:
            new_params["kb_unpin"] = unpins
        if llm_id:
            new_params["llm_id"] = llm_id
        if reasoning:
            new_params["reasoning"] = reasoning
        if extra_params:
            new_params.update(extra_params)

        params_changed = new_params != existing_ann.params
        eff_pins = cls.extract_list(new_params, "kb_pin")
        eff_unpins = cls.extract_list(new_params, "kb_unpin")
        eff_llm_id: str | None = new_params.get("llm_id")
        eff_reasoning: str | None = new_params.get("reasoning")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        md_path = cursor.md_path()
        pre_retry_snapshot = md_path.read_text(encoding="utf-8")
        op = cls(session.new_storage(owner=owner), narrative)

        def _restore_pre_retry() -> None:
            op.storage.write_file(md_path, pre_retry_snapshot)

        committed = False
        try:
            op.write_discard(cursor, existing_ann, updated_params=new_params if params_changed else None)

            mention_ids = cls.mention_pins(
                new_params.get("prompt") if isinstance(new_params.get("prompt"), str) else None,
                session.project_root,
            )
            if mention_ids:
                existing_pins = cls.extract_list(new_params, "kb_pin")
                new_params["kb_pin"] = existing_pins + mention_ids
            with_id = new_params.get("with_kb_id")
            with_extra = (
                [str(with_id).strip()]
                if isinstance(with_id, str) and str(with_id).strip()
                else []
            )
            crawl_result, ctx, resolved = cls.crawl_with_modalities(
                cls.crawl_spec(
                    cursor,
                    new_params,
                    session=session,
                    narrative=narrative,
                    extra_pins=cls.merge_extra_pin_ids(
                        eff_pins, list(mention_ids), with_extra
                    ),
                    extra_unpins=eff_unpins,
                    storage=op.storage,
                    participants=cls.participants_for_crawl(new_params),
                ),
                new_params,
                session=session,
                narrative=narrative,
            )
            cls.attach_prompt_component(
                crawl_result,
                new_params.get("prompt") if isinstance(new_params.get("prompt"), str) else None,
            )
            cls.enrich_params(crawl_result, new_params)
            fresh_ann = op.find_open_annotation(cursor)
            if fresh_ann is None:
                raise OperatorError("lost annotation after discard")

            messages = op.build_messages(
                crawl_result,
                new_params,
                session=session,
                narrative=narrative,
                resolved_modalities=resolved,
            )
            if feedback and previous_content:
                if (
                    len(messages) >= 3
                    and messages[-1]["role"] == "user"
                    and messages[-2]["role"] == "assistant"
                ):
                    # Multi-turn: the last assistant turn came from earlier
                    # conversation history (e.g. a committed write block) but the
                    # user's retry feedback refers to the *pending* write's content
                    # (previous_content).  Replace both trailing turns so the LLM
                    # sees the correct previous attempt + feedback.
                    from lens.core.prompts import PromptStore as _PS
                    feedback_text = _PS(session.project_root).format(
                        "shared.retry_feedback_template", feedback=feedback
                    )
                    messages[-2] = {"role": "assistant", "content": previous_content}
                    messages[-1] = {"role": "user", "content": feedback_text}
                else:
                    messages.extend(build_feedback_messages(previous_content, feedback, session.project_root))

            retry_override = cls._inline_command_tools_bundle(
                session.project_root, new_params
            )
            retry_tools = retry_override.tools if retry_override is not None else None
            retry_handlers = (
                retry_override.handlers if retry_override is not None else None
            )
            retry_tools, retry_handlers = merge_modality_command_tools(
                retry_tools, retry_handlers, resolved, ctx
            )

            artifacts = await cls.stream_output(
                messages,
                session.project_root,
                eff_llm_id,
                on_token,
                cancel_event=cancel_event,
                operator_name=cls.name,
                reasoning=eff_reasoning,
                tools=retry_tools,
                command_tool_handlers=retry_handlers,
            )

            if artifacts.interrupted:
                if not committed:
                    _restore_pre_retry()
                return InlineGenerationResult(outcome="interrupted")

            if not artifacts.has_content():
                raise OperatorError("no content generated")

            pending = PendingInlinePersist(
                mode="append",
                cursor=cursor,
                tag="",
                artifacts=artifacts,
                verbatim_prefix=op.content_prefix_for_fresh(new_params),
                existing_ann=fresh_ann,
                owner=owner,
                narrative=narrative,
                operator_name=cls.name,
            )
            committed = True
            return InlineGenerationResult(
                outcome="ok",
                pending=pending,
                resolved=resolved,
                modality_context=ctx,
            )
        except LLMError as e:
            if not committed:
                _restore_pre_retry()
            raise OperatorError(f"LLM error: {e}") from e
        except OperatorError:
            if not committed:
                _restore_pre_retry()
            raise
        except Exception:
            if not committed:
                _restore_pre_retry()
            raise

    # ------------------------------------------------------------------
    # Mutation flow orchestrator (edit, …)
    # ------------------------------------------------------------------

    @classmethod
    async def run_mutation(
        cls,
        *,
        session: ProjectSession,
        node: NarrativeNode,
        rel_path: str,
        ann_id: str,
        start_line: int,
        end_line: int,
        prompt: str | None,
        manual: bool = False,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Run the text-replacement flow (fresh / retry / update-retry).

        Raises :class:`OperatorError` on user-visible failures.
        """
        llm_id, reasoning, _ = apply_pinned_invocation(
            slug=cls.name,
            project_root=session.project_root,
            focus_node=node,
            narrative=None,
            llm_id=llm_id,
            reasoning=reasoning,
            extra_params=None,
        )
        effective_prompt = None if manual else prompt
        if effective_prompt:
            try:
                effective_prompt = cls.transform_storable_prompt(
                    effective_prompt, session=session, cursor=node
                )
            except DiceError as e:
                raise ValidationError(str(e)) from e
        mention_pins = cls.mention_pins(effective_prompt, session.project_root)
        if mention_pins:
            pins = pins + mention_pins

        file_path = node.md_path()
        owner = cls.owner_id(ann_id, rel_path)
        narrative_root = NarrativeNode(narrative_root=node.narrative_root, key_path=())

        probe_storage = session.new_storage()
        has_pending = probe_storage.has_pending()
        pending_owner = probe_storage.detect_pending_owner() if has_pending else None
        is_owner = (pending_owner == owner) if has_pending else False

        if manual and retry:
            raise ValidationError("retry is not supported in replace mode")

        if retry and not is_owner:
            raise ValidationError(f"no pending {cls.name} transaction to retry")

        params: dict[str, Any] = {}
        if manual:
            params["manual"] = True
            if prompt is not None:
                params["prompt"] = prompt
        elif effective_prompt:
            params["prompt"] = effective_prompt
        if reasoning:
            params["reasoning"] = reasoning

        if retry:
            await cls._do_retry_mutation(
                session, node, narrative_root, file_path,
                rel_path, ann_id, owner, pins, unpins, llm_id, params,
                probe_storage, on_token=on_token, cancel_event=cancel_event,
            )
        else:
            if has_pending and not is_owner:
                session.new_storage().stage_all()
            await cls._do_fresh_mutation(
                session, node, narrative_root, file_path,
                rel_path, ann_id, owner, start_line, end_line,
                pins, unpins, llm_id, params,
                on_token=on_token,
                cancel_event=cancel_event,
            )

    @classmethod
    async def _do_fresh_mutation(
        cls,
        session: ProjectSession,
        node: NarrativeNode,
        narrative_root: NarrativeNode,
        file_path: Path,
        rel_path: str,
        ann_id: str,
        owner: NarrativeAddress,
        start_line: int,
        end_line: int,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        params: dict[str, Any],
        on_token: Callable[[str], Awaitable[None]] | None = None,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        manual = params.get("manual", False)
        prompt = params.get("prompt")

        if not manual and not prompt:
            raise ValidationError("a prompt is required for a fresh edit")
        if manual and prompt is None:
            raise ValidationError("replacement text is required in replace mode")

        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        anns = parse_annotations(text)
        for a in anns:
            if start_line <= a.line_start <= end_line:
                raise ValidationError(
                    f"line range contains existing annotation at line {a.line_start}"
                )

        selected_text = "\n".join(lines[start_line - 1 : end_line])
        passage_before = strip_markdown_comments(
            "\n".join(lines[: start_line - 1])
        ).strip()

        op = cls(session.new_storage(owner=owner), narrative_root)
        op.start_mutation(file_path, start_line, end_line, ann_id, params)

        if manual:
            op.propose_mutation(file_path, ann_id, prompt or "")
            print(
                f"Proposed manual replace for {rel_path} lines {start_line}-{end_line}",
                file=sys.stderr,
            )
            return

        crawl_result, ctx, resolved = cls.crawl_with_modalities(
            cls.crawl_spec(
                node,
                params,
                session=session,
                narrative=narrative_root,
                extra_pins=pins,
                extra_unpins=unpins,
                storage=op.storage,
                current_passage_override=passage_before or "",
            ),
            params,
            session=session,
            narrative=narrative_root,
        )
        build_params = dict(params)
        build_params["target"] = selected_text
        messages = op.build_messages(
            crawl_result,
            build_params,
            session=session,
            narrative=narrative_root,
            resolved_modalities=resolved,
        )

        mut_reasoning: str | None = params.get("reasoning")
        try:
            artifacts = await cls.stream_output(
                messages,
                session.project_root,
                llm_id,
                on_token,
                cancel_event=cancel_event,
                operator_name=cls.name,
                reasoning=mut_reasoning,
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted or not artifacts.has_content():
            return

        artifacts, _refine_warnings = await cls.apply_modality_post_refine(
            session,
            artifacts,
            resolved=resolved,
            ctx=ctx,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        op.propose_mutation(
            file_path,
            ann_id,
            compose_for_operator(artifacts, cls.name),
        )
        print(
            f"Proposed edit for {rel_path} lines {start_line}-{end_line}",
            file=sys.stderr,
        )

    @classmethod
    async def _do_retry_mutation(
        cls,
        session: ProjectSession,
        node: NarrativeNode,
        narrative_root: NarrativeNode,
        file_path: Path,
        rel_path: str,
        ann_id: str,
        owner: NarrativeAddress,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        params: dict[str, Any],
        probe_storage: Storage,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        # When a prompt is supplied on --retry, treat it as feedback rather than
        # a replacement for the stored instruction.  Capture the previously
        # proposed content before rolling back so we can append it as an
        # assistant turn alongside the feedback.
        feedback: str | None = params.get("prompt") or None
        pre_rollback_text: str | None = None
        if feedback and file_path.exists():
            pre_rollback_text = file_path.read_text(encoding="utf-8")

        probe_storage.rollback()

        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        anns = parse_annotations(text)
        open_ann: ParsedAnnotation | None = None
        close_ann: ParsedAnnotation | None = None
        for a in anns:
            if a.id != ann_id:
                continue
            if not a.closing and not a.self_closing:
                open_ann = a
            elif a.closing:
                close_ann = a
        if open_ann is None or close_ann is None:
            raise OperatorError("claim tags not found after rollback")

        selected_text = "\n".join(
            lines[open_ann.line_end : close_ann.line_start - 1]
        ).strip()
        passage_before = strip_markdown_comments(
            "\n".join(lines[: open_ann.line_start - 1])
        ).strip()

        # Extract previous proposal from the pre-rollback file.  propose_mutation
        # writes: before_prefix + new_content + "\n" + after_suffix, so we can
        # recover new_content by stripping the known prefix and suffix lengths.
        previous_proposal: str | None = None
        if feedback and pre_rollback_text is not None:
            before_prefix = _lines_prefix(lines[: open_ann.line_start - 1])
            after_suffix = "\n".join(lines[close_ann.line_end :])
            start = len(before_prefix)
            end = len(pre_rollback_text) - len(after_suffix) if after_suffix else len(pre_rollback_text)
            previous_proposal = pre_rollback_text[start:end].rstrip("\n") or None

        # Recover stored params from the claim tag.  Do NOT overwrite the stored
        # prompt — feedback is a separate message turn, not a new annotation param.
        effective_params = dict(open_ann.params)
        if params.get("reasoning"):
            effective_params["reasoning"] = params["reasoning"]
        if not effective_params.get("prompt"):
            raise ValidationError("no prompt found in claim tag and none provided")
        effective_params["target"] = selected_text

        op = cls(session.new_storage(owner=owner), narrative_root)
        crawl_result, ctx, resolved = cls.crawl_with_modalities(
            cls.crawl_spec(
                node,
                effective_params,
                session=session,
                narrative=narrative_root,
                extra_pins=pins,
                extra_unpins=unpins,
                storage=op.storage,
                current_passage_override=passage_before or "",
            ),
            effective_params,
            session=session,
            narrative=narrative_root,
        )
        messages = op.build_messages(
            crawl_result,
            effective_params,
            session=session,
            narrative=narrative_root,
            resolved_modalities=resolved,
        )
        if feedback and previous_proposal:
            messages.extend(build_feedback_messages(previous_proposal, feedback, session.project_root))
        retry_reasoning: str | None = effective_params.get("reasoning")

        try:
            artifacts = await cls.stream_output(
                messages,
                session.project_root,
                llm_id,
                on_token,
                cancel_event=cancel_event,
                operator_name=cls.name,
                reasoning=retry_reasoning,
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted or not artifacts.has_content():
            return

        artifacts, _refine_warnings = await cls.apply_modality_post_refine(
            session,
            artifacts,
            resolved=resolved,
            ctx=ctx,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        op.propose_mutation(
            file_path,
            ann_id,
            compose_for_operator(artifacts, cls.name),
        )
        print(f"Retried edit for {rel_path}", file=sys.stderr)
