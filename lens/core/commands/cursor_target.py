"""Resolving "which cursor should I report on" for the read-only reporters.

``lens explain`` and ``lens spine`` both answer a question about a point in the
narrative rather than writing to it, and both accept the same optional target:
nothing (the cursor), an address, or an address plus a line.  The resolution is
shared here for the same reason :mod:`lens.core.operator_detect` is shared —
two reporters that disagree about where the cursor is are worse than one.
"""

from __future__ import annotations

from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, resolve_address, unknown_node_hint


def resolve_report_target(
    session: ProjectSession, address: str | None, line: int | None
) -> tuple[NarrativeNode, str, int | None]:
    """Resolve *address* (or the cursor) to a node, its address string, and a line.

    An explicit *line* wins over an ``@line`` suffix on the address, so
    ``lens explain /ch1@4 7`` reports as of line 7. ``.`` is the cursor, the
    spelling anyone reaches for first.
    """
    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative (run 'lens use <slug>' first)")

    if address is None or address == ".":
        node = narrative.find_cursor()
        return node, str(node.to_address()), line

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        raise LensException(f"invalid address: {e}") from e
    try:
        resolved = resolve_address(addr, session.project_root)
        node = resolved.node_only().to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        raise LensException(str(e)) from e
    if not node.exists():
        hint = unknown_node_hint(addr, session.project_root)
        raise LensException(
            f"node does not exist: {address}" + (f" — {hint}" if hint else "")
        )

    effective_line = line if line is not None else addr.line
    return node, str(node.to_address()), effective_line


def current_passage_override(node: NarrativeNode, line: int) -> str:
    """Raw text of *node* truncated at *line*.

    Deliberately raw: ``crawl`` expands mentions and strips comments from an
    override, and it is the only place that knows the resolved pins, so
    expanding here would report a block the real prompt suppresses as
    already-pinned.  Truncating first is what makes ``--line`` answer "as of
    that point" — a mention written later is not in scope yet, and one written
    earlier is live or expired according to the turns above *line*.
    """
    try:
        raw = node.md_path().read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise LensException(f"node has no file: {node.path_str()}") from e
    lines = raw.split("\n")
    if line < 1 or line > len(lines):
        raise LensException(
            f"line {line} is out of range for '{node.path_str()}' (1–{len(lines)})"
        )
    return "\n".join(lines[:line])
