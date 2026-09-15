"""Core implementation of ``lens spine`` — the story so far, root to cursor.

A Lens prompt does not carry the whole narrative: it carries the *spine*, the
chain of nodes from the narrative root down to the cursor, where every ancestor
contributes its own prose (in a collated tree, its summary) and only the cursor
node contributes live text.  That is the story the model is working from, and it
is not something a reader can reconstruct by opening files: the chain is spread
across one file per level, each one carrying operator annotations that never
reach a model.

So this command reports it.  It runs the same :func:`~lens.core.context.crawl`
an operator would, then prints the narrative components instead of assembling
them into a prompt — no drift between "the story so far" and what `write` is
about to read.  Knowledge, task framing and modalities are crawled (a mention
already covered by a pin must be suppressed here exactly as the prompt
suppresses it) and then dropped; ``lens explain`` is the command that reports
those.

Read-only by construction: ``Storage`` is created with ``owner=None`` and never
written to, so no transaction is opened and no LLM configuration is needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from lens.core.commands.cursor_target import (
    current_passage_override,
    resolve_report_target,
)
from lens.core.context import CrawlResult, CrawlSpec, ancestor_chain, crawl
from lens.core.exceptions import LensException
from lens.core.operator_detect import (
    detect_open_session_operator,
    detect_operator_name,
)
from lens.core.project import ProjectSession

DEFAULT_CHARS_PER_TOKEN = 4
"""Rough divisor for the token estimate; byte counts are exact.

Same approximation ``lens explain`` documents — the two report the same
narrative text, so they must divide it the same way.
"""

ROLE_SUMMARY = "summary"
ROLE_CURRENT = "current"


@dataclass(frozen=True)
class SpineNode:
    """One node on the spine, and what it contributes to the prompt."""

    address: str
    depth: int
    role: str
    text: str
    bytes: int
    tokens: int
    lines: int
    has_file: bool
    truncated: bool = False

    @property
    def contributes(self) -> bool:
        """Whether this node puts anything in front of the model.

        A node on the spine that holds only front matter and annotations is
        skipped by ``crawl`` entirely.  It is still listed here — an empty
        ancestor is usually the answer to "why does the model not know that".
        """
        return bool(self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "depth": self.depth,
            "role": self.role,
            "text": self.text,
            "bytes": self.bytes,
            "tokens": self.tokens,
            "lines": self.lines,
            "has_file": self.has_file,
            "contributes": self.contributes,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class SpineReport:
    """The narrative spine at a cursor, as the next generation would read it."""

    narrative: str
    address: str
    line: int | None
    operator: str | None
    open_session: str | None
    nodes: tuple[SpineNode, ...]
    chars_per_token: int

    @property
    def contributing(self) -> tuple[SpineNode, ...]:
        return tuple(n for n in self.nodes if n.contributes)

    @property
    def total_bytes(self) -> int:
        return sum(n.bytes for n in self.nodes)

    @property
    def total_tokens(self) -> int:
        return sum(n.tokens for n in self.nodes)

    @property
    def total_lines(self) -> int:
        return sum(n.lines for n in self.nodes)

    @property
    def text(self) -> str:
        """Every contributing node's prose, spine order, blank-line separated."""
        return "\n\n".join(n.text for n in self.contributing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative": self.narrative,
            "address": self.address,
            "line": self.line,
            "operator": self.operator,
            "open_session": self.open_session,
            "nodes": [n.to_dict() for n in self.nodes],
            "totals": {
                "bytes": self.total_bytes,
                "tokens": self.total_tokens,
                "lines": self.total_lines,
                "nodes": len(self.nodes),
                "contributing_nodes": len(self.contributing),
            },
            "chars_per_token": self.chars_per_token,
        }


def _tokens(text: str, chars_per_token: int) -> int:
    return math.ceil(len(text.encode("utf-8")) / chars_per_token) if text else 0


def _line_count(text: str) -> int:
    return len(text.split("\n")) if text else 0


def spine_report(
    session: ProjectSession,
    *,
    address: str | None = None,
    line: int | None = None,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> SpineReport:
    """Reconstruct the narrative spine at a cursor.

    *address* defaults to the current cursor; pass one to see the spine as it
    would be assembled somewhere else in the tree.  *line* (or an ``@line``
    suffix on the address) truncates the cursor node's own passage there, so the
    report answers "what had the story said by that point".

    Nothing is written and no model is called.
    """
    if chars_per_token < 1:
        raise LensException("--chars-per-token must be at least 1")

    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative (run 'lens use <slug>' first)")

    node, address_str, effective_line = resolve_report_target(session, address, line)

    storage = session.new_storage(owner=None)
    spec_kwargs: dict[str, Any] = {"storage": storage}
    if effective_line is not None:
        spec_kwargs["current_passage_override"] = current_passage_override(
            node, effective_line
        )

    # No operator: the spine is the same chain of nodes whichever operator runs
    # at the cursor, and binding one here would only add its auto-pins to
    # knowledge this report discards.  `crawl` is still asked for knowledge, so
    # in-place mention expansion resolves against the real pin set.
    crawl_result = crawl(CrawlSpec.of(node, **spec_kwargs))

    texts = _narrative_text_by_node(crawl_result)
    nodes: list[SpineNode] = []
    for depth, spine_node in enumerate(ancestor_chain(node)):
        is_cursor = spine_node.key_path == node.key_path
        key = _CURSOR_KEY if is_cursor else spine_node.path_str()
        # Stripped: a component keeps the blank lines that sat around the
        # annotations comment-stripping removed, and `assemble_prompt` strips
        # them again when it frames the block.  Reporting the trimmed text
        # keeps the byte count and what is printed describing one thing.
        text = texts.get(key, "").strip()
        nodes.append(
            SpineNode(
                address=str(spine_node.to_address()),
                depth=depth,
                role=ROLE_CURRENT if is_cursor else ROLE_SUMMARY,
                text=text,
                bytes=len(text.encode("utf-8")),
                tokens=_tokens(text, chars_per_token),
                lines=_line_count(text),
                has_file=spine_node.exists(),
                truncated=is_cursor and effective_line is not None,
            )
        )

    return SpineReport(
        narrative=narrative.narrative_root.name,
        address=address_str,
        line=effective_line,
        operator=detect_operator_name(node),
        open_session=detect_open_session_operator(node),
        nodes=tuple(nodes),
        chars_per_token=chars_per_token,
    )


_CURSOR_KEY = "\x00cursor"
"""Key for the cursor's own contribution.

The current passage may come from a ``current_passage_override`` component,
which carries no node metadata, so it cannot be keyed by path like the
summaries are — and a node path could in principle collide with a sentinel made
of ordinary characters.
"""


def _narrative_text_by_node(crawl_result: CrawlResult) -> dict[str, str]:
    """Map spine node path -> the text that node contributed to the prompt.

    Read off the crawl's own components rather than re-reading the files, so
    comment stripping, mention expansion and anchor slicing are whatever the
    prompt got, not a second implementation of them.  ``crawl`` never emits a
    summary component for the cursor node itself, so the two kinds cannot
    collide over one path.
    """
    by_node: dict[str, str] = {}
    for component in crawl_result.graph.components:
        if "llm" not in component.visibility:
            continue
        if component.kind == "narrative_summary":
            node_path = component.metadata.get("node")
            if node_path:
                by_node[node_path] = component.text
        elif component.kind == "current_narrative":
            by_node[_CURSOR_KEY] = component.text
    return by_node
