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
from abc import ABC
from pathlib import Path
from typing import Any, ClassVar

import yaml

from lens.address import NarrativeAddress
from lens.annotations import (
    ParsedAnnotation,
    parse_annotations,
)
from lens.narrative import NarrativeNode, NodeSegment, parse_segments
from lens.storage import Storage


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
    ) -> None:
        """Wrap lines *start_line*..*end_line* (1-based, inclusive) in claim
        tags, then force-stage so the claim is committed to the index.

        After this call a new pending transaction can be opened with
        :meth:`propose_mutation`.
        """
        text = file_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        before = lines[: start_line - 1]
        claimed = lines[start_line - 1 : end_line]
        after = lines[end_line:]
        open_tag = self.build_open_tag(id)
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
