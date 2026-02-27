"""Extensible operator base class for Lens.

An operator is a module that manipulates narrative text and structure via
traceable annotation patterns.  Every operator subclass declares a ``name``
(used in annotation tags like ``[name:id]: #``) and whether an annotation
ID is required (``requires_id``).

Operators construct a :class:`~lens.storage.Storage` instance with their
canonical *owner address* so that the storage layer can enforce single-pending-
transaction semantics automatically.  The base class provides:

* **Tag builders** – produce well-formed annotation strings.
* **Annotation readers** – find this operator's annotations / segments.
* **Node write helpers** – append to narrative nodes via Storage.
* **Mode helpers** – composable utilities for the three operating modes
  described in the design document.
"""

from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar
from collections.abc import Callable, Awaitable

import yaml

from lens.core.address import NarrativeAddress
from lens.core.annotations import (
    ParsedAnnotation,
    parse_annotations,
    strip_markdown_comments,
)
from lens.core.context import CrawlResult, assemble_prompt, crawl
from lens.core.llm import LLMError, generate
from lens.core.narrative import NarrativeNode, NodeSegment, parse_segments
from lens.core.project import ProjectSession
from lens.core.storage import Storage


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

    def __init__(self, storage: Storage, narrative_root: NarrativeNode) -> None:
        self.storage = storage
        self.narrative_root = narrative_root

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
        yaml_text = yaml.dump(params, default_flow_style=False).rstrip("\n")
        indented = re.sub(r"^", "  ", yaml_text, flags=re.MULTILINE)
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
        suffix = summary + "\n\n" + close + "\n" if summary else close + "\n"
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
        """Multi-step inline: open tag with ``steps: 1``, no close tag."""
        p = dict(params) if params else {}
        p["steps"] = 1
        tag = self.build_open_tag(id, p)
        self.append_to_node(node, tag + "\n")

    def continue_inline(
        self,
        node: NarrativeNode,
        id: str | None,
        content: str,
    ) -> None:
        """Increment the ``steps`` counter and append *content*.

        Reads the node, finds the open annotation, bumps ``steps``,
        re-writes the file.
        """
        md = node.md_path()
        text = md.read_text(encoding="utf-8")
        anns = self.find_my_annotations(text)
        target: ParsedAnnotation | None = None
        for a in anns:
            if a.id == id and not a.closing and not a.self_closing:
                target = a
        if target is None:
            raise ValueError(
                f"No open [{self.name}:{id}] annotation found in {node.path_str()}"
            )
        old_steps = target.params.get("steps", 1)
        new_params = dict(target.params)
        new_params["steps"] = int(old_steps) + 1
        new_tag = self.build_open_tag(id, new_params)
        lines = text.split("\n")
        before = lines[: target.line_start - 1]
        after = lines[target.line_end :]
        rebuilt = "\n".join(before) + "\n" + new_tag + "\n" + content + "\n" + "\n".join(after)
        self.storage.write_file(md, rebuilt)

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
            "\n".join(before)
            + "\n"
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
        rebuilt = "\n".join(before) + "\n" + new_content + "\n" + "\n".join(after)
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
        rebuilt = "\n".join(before) + "\n" + "\n".join(claimed) + "\n" + "\n".join(after)
        self.storage.write_file(file_path, rebuilt)
        self.storage.stage_all()


# ---------------------------------------------------------------------------
# ContextAwareOperator — LLM-powered abstract intermediate base
# ---------------------------------------------------------------------------


class ContextAwareOperator(Operator):
    """Abstract intermediate base for operators that stream LLM output.

    Subclasses must implement :attr:`system_prompt` and
    :meth:`build_instruction`. This class provides all shared I/O helpers
    and the :meth:`run_inline` / :meth:`run_mutation` flow orchestrators.
    """

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def build_instruction(self, params: dict[str, Any]) -> str: ...

    # ------------------------------------------------------------------
    # Static helpers
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
    async def stream_output(
        messages: list[dict[str, str]],
        project_root: Path,
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Stream LLM output and return the full collected text."""
        chunks: list[str] = []
        interrupted = False
        try:
            async for chunk in generate(messages, project_root, llm_id=llm_id):
                if on_token:
                    await on_token(chunk)
                chunks.append(chunk)
        except KeyboardInterrupt:
            interrupted = True
        if interrupted and not chunks:
            return ""
        return "".join(chunks)

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
        """Increment ``steps``, preserve existing content, append new content before close tag."""
        md = node.md_path()
        text = md.read_text(encoding="utf-8")
        new_params = dict(ann.params)
        new_params["steps"] = int(ann.params.get("steps", 1)) + 1
        new_tag = self.build_open_tag(ann.id, new_params)
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
        """Remove generated content, reset steps to 0, optionally update params.

        Steps is set to 0 so that the subsequent ``write_append`` call lands
        at ``steps: 1`` (one generation for one step).
        """
        md = node.md_path()
        text = md.read_text(encoding="utf-8")
        params = dict(updated_params if updated_params is not None else ann.params)
        params["steps"] = 0
        new_tag = self.build_open_tag(ann.id, params)
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
    ) -> None:
        """Run the inline-appending flow (fresh / continue / retry / update-retry).

        Raises :class:`OperatorError` on user-visible failures.
        """
        cursor = narrative.find_cursor()
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
            if prompt or pins or unpins or (
                llm_id and llm_id != existing_ann.params.get("llm_id")
            ):
                await cls._do_update_retry(
                    session, narrative, cursor, rel_path,
                    existing_ann, prompt, pins, unpins, llm_id,
                )
            elif retry:
                await cls._do_retry(
                    session, narrative, cursor, rel_path,
                    existing_ann,
                )
            else:
                await cls._do_continue(
                    session, narrative, cursor, rel_path,
                    existing_ann,
                )
        else:
            await cls._do_fresh_inline(
                session, narrative, cursor, rel_path,
                prompt, pins, unpins, llm_id,
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
    ) -> None:
        ann_params: dict[str, Any] = {"steps": 1}
        if prompt:
            ann_params["prompt"] = prompt
        if pins:
            ann_params["kb_pin"] = pins
        if unpins:
            ann_params["kb_unpin"] = unpins
        if llm_id:
            ann_params["llm_id"] = llm_id

        current_text = cursor.md_path().read_text(encoding="utf-8")
        ann_line = cls.ann_line_for_append(current_text)
        owner = cls.owner_id(None, rel_path, line=ann_line)

        probe_op = cls(session.new_storage(), narrative)
        tag = probe_op.build_open_tag(None, ann_params)

        crawl_result = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        messages = probe_op.build_messages(crawl_result, ann_params)

        try:
            content = await cls.stream_output(messages, session.project_root, llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

        op = cls(session.new_storage(owner=owner), narrative)
        op.write_start(cursor, tag, content)
        print(f"Written to {cursor.path_str()}", file=sys.stderr)

    @classmethod
    async def _do_continue(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        rel_path: str,
        existing_ann: ParsedAnnotation,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        ann_pins = cls.extract_list(existing_ann.params, "kb_pin")
        ann_unpins = cls.extract_list(existing_ann.params, "kb_unpin")
        ann_llm_id: str | None = existing_ann.params.get("llm_id")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)

        crawl_result = crawl(cursor, extra_pins=ann_pins, extra_unpins=ann_unpins)
        messages = op.build_messages(crawl_result, existing_ann.params)

        try:
            content = await cls.stream_output(messages, session.project_root, ann_llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

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
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        ann_pins = cls.extract_list(existing_ann.params, "kb_pin")
        ann_unpins = cls.extract_list(existing_ann.params, "kb_unpin")
        ann_llm_id: str | None = existing_ann.params.get("llm_id")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)
        op.write_discard(cursor, existing_ann)

        crawl_result = crawl(cursor, extra_pins=ann_pins, extra_unpins=ann_unpins)
        fresh_ann = op.find_open_annotation(cursor)
        if fresh_ann is None:
            raise OperatorError("lost annotation after discard")

        messages = op.build_messages(crawl_result, existing_ann.params)

        try:
            content = await cls.stream_output(messages, session.project_root, ann_llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

        op.write_append(cursor, fresh_ann, content)
        print(f"Retried {cls.name} in {cursor.path_str()}", file=sys.stderr)

    @classmethod
    async def _do_update_retry(
        cls,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        rel_path: str,
        existing_ann: ParsedAnnotation,
        prompt: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
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

        eff_pins = cls.extract_list(new_params, "kb_pin")
        eff_unpins = cls.extract_list(new_params, "kb_unpin")
        eff_llm_id: str | None = new_params.get("llm_id")

        owner = cls._owner_for_ann(existing_ann, rel_path)
        op = cls(session.new_storage(owner=owner), narrative)
        op.write_discard(cursor, existing_ann, updated_params=new_params)

        crawl_result = crawl(cursor, extra_pins=eff_pins, extra_unpins=eff_unpins)
        fresh_ann = op.find_open_annotation(cursor)
        if fresh_ann is None:
            raise OperatorError("lost annotation after discard")

        messages = op.build_messages(crawl_result, new_params)

        try:
            content = await cls.stream_output(messages, session.project_root, eff_llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

        op.write_append(cursor, fresh_ann, content)
        print(f"Updated and retried {cls.name} in {cursor.path_str()}", file=sys.stderr)

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
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Run the text-replacement flow (fresh / retry / update-retry).

        Raises :class:`OperatorError` on user-visible failures.
        """
        file_path = node.md_path()
        owner = cls.owner_id(ann_id, rel_path)
        narrative_root = NarrativeNode(narrative_root=node.narrative_root, key_path=())

        probe_storage = session.new_storage()
        has_pending = probe_storage.has_pending()
        pending_owner = probe_storage.detect_pending_owner() if has_pending else None
        is_owner = (pending_owner == owner) if has_pending else False

        if retry and not is_owner:
            raise OperatorError(f"no pending {cls.name} transaction to retry")

        params: dict[str, Any] = {}
        if prompt:
            params["prompt"] = prompt

        if retry:
            await cls._do_retry_mutation(
                session, node, narrative_root, file_path,
                rel_path, ann_id, owner, pins, unpins, llm_id, params,
                probe_storage,
            )
        else:
            await cls._do_fresh_mutation(
                session, node, narrative_root, file_path,
                rel_path, ann_id, owner, start_line, end_line,
                pins, unpins, llm_id, params,
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
    ) -> None:
        if not params.get("prompt"):
            raise OperatorError("a prompt is required for a fresh edit")

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
        # params stored in claim tag contain only the prompt, not the target
        # (the target is always recoverable from between the claim tags on retry)
        op.start_mutation(file_path, start_line, end_line, ann_id, params)

        crawl_result = crawl(node, extra_pins=pins, extra_unpins=unpins)
        crawl_result = CrawlResult(
            knowledge=crawl_result.knowledge,
            previous_summaries=crawl_result.previous_summaries,
            current_content=passage_before or None,
        )
        build_params = dict(params)
        build_params["target"] = selected_text
        messages = op.build_messages(crawl_result, build_params)

        try:
            content = await cls.stream_output(messages, session.project_root, llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

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
            knowledge=crawl_result.knowledge,
            previous_summaries=crawl_result.previous_summaries,
            current_content=passage_before or None,
        )
        messages = op.build_messages(crawl_result, effective_params)

        try:
            content = await cls.stream_output(messages, session.project_root, llm_id, on_token)
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if not content.strip():
            raise OperatorError("no content generated")

        op.propose_mutation(file_path, ann_id, content)
        print(f"Retried edit for {rel_path}", file=sys.stderr)
