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
   :func:`~lens.core.llm.generate_stream` with optional tools. Result is
   either plain text or a tool call.

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
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, cast
from collections.abc import Callable, Awaitable
import yaml


from lens.core.address import NarrativeAddress
from lens.core.annotations import (
    ParsedAnnotation,
    parse_annotations,
    strip_markdown_comments,
)
from lens.core.command_tools import CommandToolFn
from lens.core.context import CrawlResult, assemble_prompt, crawl
from lens.core.dice import DiceError, substitute_rolls
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError, build_command_tools_bundle, generate_text
from lens.core.narrative import NarrativeNode, NodeSegment, parse_segments
from lens.core.project import ProjectSession
from lens.core.storage import Storage

_AT_MENTION_RE = re.compile(
    r"@([a-zA-Z0-9_-]+\.[a-zA-Z0-9_.-]+)(?=\s|$)", re.MULTILINE
)


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


class OperatorError(Exception):
    """User-visible error raised by operator flow orchestrators."""


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
        """Close a sub-node by appending *summary* and a close tag to *parent*."""
        close = self.build_close_tag(id)
        if summary:
            quoted_summary = "\n".join(f"> {line}" for line in summary.splitlines())
            suffix = quoted_summary + "\n\n" + close + "\n"
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
    ) -> str:
        """Stream LLM output and return the full collected text."""
        return await generate_text(
            messages,
            project_root,
            llm_id=llm_id,
            tools=None,
            cancel_event=cancel_event,
            on_preview=on_token,
            interrupt_policy="return_empty",
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

    def write_start(self, node: NarrativeNode, tag: str, content: str) -> None:
        """Atomically write an open tag, generated content, and close tag to the node."""
        md = node.md_path()
        current = md.read_text(encoding="utf-8")
        sep = "\n" if current.endswith("\n") else "\n\n"
        close_tag = self.build_close_tag(None)
        self.storage.write_file(
            md, current + sep + tag + "\n\n" + content.rstrip() + "\n\n" + close_tag + "\n"
        )

    def write_append(
        self, node: NarrativeNode, ann: ParsedAnnotation, new_content: str
    ) -> None:
        """Preserve existing content, append new content before close tag."""
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

    def build_messages(
        self,
        crawl_result: CrawlResult,
        params: dict[str, Any],
    ) -> list[dict[str, str]]:
        return assemble_prompt(
            crawl_result,
            system_prompt=self.system_prompt,
            instruction=self.build_instruction(params),
        )

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
        on_token: Callable[[str], Awaitable[None]] | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        _cursor_override: NarrativeNode | None = None,
        empty_prompt_ok: bool = False,
    ) -> None:
        """Run the inline flow (fresh / retry / update-retry).

        *empty_prompt_ok* is for operators (e.g. play) that persist the user
        turn outside the annotation and call the LLM with instruction-only
        context; they pass ``prompt=None`` into this orchestrator.

        Raises :class:`OperatorError` on user-visible failures.
        """
        if prompt:
            try:
                prompt = substitute_rolls(prompt)
            except DiceError as e:
                raise OperatorError(str(e)) from e

        mention_pins = cls.mention_pins(prompt, session.project_root)
        if mention_pins:
            pins = pins + mention_pins

        cursor = _cursor_override if _cursor_override is not None else narrative.find_cursor()
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
            raise OperatorError(f"no pending {cls.name} transaction to retry")

        if is_owner:
            assert existing_ann is not None
            if retry:
                # --retry: discard and regenerate (optionally with updated params)
                await cls._do_retry(
                    session, narrative, cursor, rel_path, existing_ann,
                    prompt=prompt, pins=pins or [], unpins=unpins or [],
                    llm_id=llm_id, extra_params=extra_params,
                    on_token=on_token, cancel_event=cancel_event,
                )
            elif prompt or pins or unpins or (
                llm_id and llm_id != existing_ann.params.get("llm_id")
            ):
                # New args without --retry → auto-commit previous, start fresh
                session.new_storage().stage_all()
                print(f"Committed pending {cls.name}. Starting fresh.", file=sys.stderr)
                await cls._do_fresh_inline(
                    session, narrative, cursor, rel_path,
                    prompt, pins, unpins, llm_id,
                    on_token=on_token,
                    extra_params=extra_params,
                    cancel_event=cancel_event,
                )
            else:
                # Previously: continue in the same annotation (steps++).
                # Now: always stage and start a new annotation.
                if not prompt and not empty_prompt_ok:
                    raise OperatorError(f"{cls.name} requires a prompt (or --retry)")
                session.new_storage().stage_all()
                await cls._do_fresh_inline(
                    session, narrative, cursor, rel_path,
                    prompt, pins, unpins, llm_id,
                    on_token=on_token,
                    extra_params=extra_params,
                    cancel_event=cancel_event,
                )
        else:
            if has_pending:
                session.new_storage().stage_all()
            await cls._do_fresh_inline(
                session, narrative, cursor, rel_path,
                prompt, pins, unpins, llm_id,
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
    ) -> None:
        ann_params: dict[str, Any] = {}
        if prompt:
            ann_params["prompt"] = prompt
        if pins:
            ann_params["kb_pin"] = pins
        if unpins:
            ann_params["kb_unpin"] = unpins
        if llm_id:
            ann_params["llm_id"] = llm_id
        if extra_params:
            ann_params.update(extra_params)

        current_text = cursor.md_path().read_text(encoding="utf-8")
        ann_line = cls.ann_line_for_append(current_text)
        owner = cls.owner_id(None, rel_path, line=ann_line)

        mention_ids = cls.mention_pins(prompt, session.project_root)
        if mention_ids:
            existing_pins = cls.extract_list(ann_params, "kb_pin")
            ann_params["kb_pin"] = existing_pins + mention_ids
        crawl_result = crawl(
            cursor,
            extra_pins=pins + mention_ids,
            extra_unpins=unpins,
        )
        cls.check_requirements(crawl_result)
        cls.enrich_params(crawl_result, ann_params)

        probe_op = cls(session.new_storage(), narrative)
        tag = probe_op.build_open_tag(None, ann_params)

        content: str = ""
        interrupted = False

        messages = probe_op.build_messages(crawl_result, ann_params)

        # ── Command tools ─────────────────────────────────────────────────
        # Operators that prioritise speed (e.g. play) opt out via
        # use_command_tools = False.
        tools_payload: list[dict[str, Any]] | None = None
        command_handlers: dict[str, CommandToolFn] | None = None
        if cls.use_command_tools:
            bundle = build_command_tools_bundle(session.project_root)
            tools_payload = bundle.tools
            command_handlers = bundle.handlers

        try:
            content = await generate_text(
                messages,
                session.project_root,
                llm_id=llm_id,
                tools=tools_payload,
                command_tool_handlers=command_handlers,
                cancel_event=cancel_event,
                on_preview=on_token,
                interrupt_policy="raise",
            )
        except KeyboardInterrupt:
            interrupted = True
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if interrupted:
            return

        if not content.strip():
            raise OperatorError("no content generated")

        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        content_prefix = op.content_prefix_for_fresh(ann_params)
        if content_prefix:
            content = content_prefix + content
        op.write_start(cursor, tag, content)

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

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)

        crawl_result = crawl(cursor, extra_pins=ann_pins, extra_unpins=ann_unpins)
        cls.enrich_params(crawl_result, existing_ann.params)
        messages = op.build_messages(crawl_result, existing_ann.params)

        try:
            content = await cls.stream_output(messages, session.project_root, ann_llm_id, on_token, cancel_event=cancel_event)
        except KeyboardInterrupt:
            return
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            return

        op.write_append(cursor, existing_ann, content)
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
        extra_params: dict[str, Any] | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        new_params: dict[str, Any] = dict(existing_ann.params)
        if prompt is not None:
            new_params["prompt"] = prompt
        if pins:
            new_params["kb_pin"] = pins
        if unpins:
            new_params["kb_unpin"] = unpins
        if llm_id:
            new_params["llm_id"] = llm_id
        if extra_params:
            new_params.update(extra_params)

        params_changed = new_params != existing_ann.params
        eff_pins = cls.extract_list(new_params, "kb_pin")
        eff_unpins = cls.extract_list(new_params, "kb_unpin")
        eff_llm_id: str | None = new_params.get("llm_id")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)
        op.write_discard(cursor, existing_ann, updated_params=new_params if params_changed else None)

        mention_ids = cls.mention_pins(
            new_params.get("prompt") if isinstance(new_params.get("prompt"), str) else None,
            session.project_root,
        )
        if mention_ids:
            existing_pins = cls.extract_list(new_params, "kb_pin")
            new_params["kb_pin"] = existing_pins + mention_ids
        crawl_result = crawl(
            cursor,
            extra_pins=eff_pins + mention_ids,
            extra_unpins=eff_unpins,
        )
        cls.enrich_params(crawl_result, new_params)
        fresh_ann = op.find_open_annotation(cursor)
        if fresh_ann is None:
            raise OperatorError("lost annotation after discard")

        messages = op.build_messages(crawl_result, new_params)

        try:
            content = await cls.stream_output(messages, session.project_root, eff_llm_id, on_token, cancel_event=cancel_event)
        except KeyboardInterrupt:
            return
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            return

        content_prefix = op.content_prefix_for_fresh(new_params)
        if content_prefix:
            content = content_prefix + content
        op.write_append(cursor, fresh_ann, content)
        print(f"Retried {cls.name} in {cursor.path_str()}", file=sys.stderr)

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
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Run the text-replacement flow (fresh / retry / update-retry).

        Raises :class:`OperatorError` on user-visible failures.
        """
        effective_prompt = None if manual else prompt
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
            raise OperatorError("retry is not supported in replace mode")

        if retry and not is_owner:
            raise OperatorError(f"no pending {cls.name} transaction to retry")

        params: dict[str, Any] = {}
        if prompt:
            params["prompt"] = prompt
        if manual:
            params["manual"] = True

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
            raise OperatorError("a prompt is required for a fresh edit")
        if manual and not prompt:
            raise OperatorError("replacement text is required in replace mode")

        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        anns = parse_annotations(text)
        for a in anns:
            if start_line <= a.line_start <= end_line:
                raise OperatorError(
                    f"line range contains existing annotation at line {a.line_start}"
                )

        selected_text = "\n".join(lines[start_line - 1 : end_line])
        passage_before = strip_markdown_comments(
            "\n".join(lines[: start_line - 1])
        ).strip()

        op = cls(session.new_storage(owner=owner), narrative_root)
        op.start_mutation(file_path, start_line, end_line, ann_id, params)

        if manual:
            assert prompt is not None  # validated above
            op.propose_mutation(file_path, ann_id, prompt)
            print(
                f"Proposed manual replace for {rel_path} lines {start_line}-{end_line}",
                file=sys.stderr,
            )
            return

        crawl_result = crawl(node, extra_pins=pins, extra_unpins=unpins)
        crawl_result = CrawlResult(
            project_root=session.project_root,
            knowledge=crawl_result.knowledge,
            previous_summaries=crawl_result.previous_summaries,
            current_content=passage_before or None,
        )
        build_params = dict(params)
        build_params["target"] = selected_text
        messages = op.build_messages(crawl_result, build_params)

        try:
            content = await cls.stream_output(messages, session.project_root, llm_id, on_token, cancel_event=cancel_event)
        except KeyboardInterrupt:
            return
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            return

        op.propose_mutation(file_path, ann_id, content)
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

        # Recover stored params from the claim tag; new prompt overrides.
        effective_params = dict(open_ann.params)
        if params.get("prompt"):
            effective_params["prompt"] = params["prompt"]
        if not effective_params.get("prompt"):
            raise OperatorError("no prompt found in claim tag and none provided")
        effective_params["target"] = selected_text

        op = cls(session.new_storage(owner=owner), narrative_root)
        crawl_result = crawl(node, extra_pins=pins, extra_unpins=unpins)
        crawl_result = CrawlResult(
            project_root=session.project_root,
            knowledge=crawl_result.knowledge,
            previous_summaries=crawl_result.previous_summaries,
            current_content=passage_before or None,
        )
        messages = op.build_messages(crawl_result, effective_params)

        try:
            content = await cls.stream_output(messages, session.project_root, llm_id, on_token, cancel_event=cancel_event)
        except KeyboardInterrupt:
            return
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            return

        op.propose_mutation(file_path, ann_id, content)
        print(f"Retried edit for {rel_path}", file=sys.stderr)
