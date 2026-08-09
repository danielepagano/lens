"""Which operator owns a cursor — shared by ``lens explain`` and ``lens stats``.

Two different questions are answered here, and they are not the same question:

``detect_open_session_operator``
    *Is a session currently open over this node?*  Only true while a session
    annotation is unclosed, because the answer gates session-close affordances
    (``play --end``, ``chat --end``) that are invalid once the session closed.

``detect_operator_name``
    *What would run at this cursor?*  Falls back to the most recent completed
    narrating block, because an inline turn closes the moment it finishes and
    that is the state a report is almost always read in.
"""

from __future__ import annotations

from lens.core.narrative import (
    NarrativeNode,
    ParsedAnnotation,
    find_unclosed_cursor_annotation,
    parse_segments,
)

SESSION_OPERATOR_NAMES: frozenset[str] = frozenset({"advance", "chat", "design", "play"})

NARRATING_OPERATOR_NAMES: frozenset[str] = SESSION_OPERATOR_NAMES | {"write"}
"""Operators that represent *what is being written here*.

Structural and mutation operators (``section``, ``collate``, ``compress``,
``edit``) are deliberately excluded: a section tag between two play turns says
something about the shape of the tree, not about what the next call will be.
"""


def _node_text(node: NarrativeNode) -> str | None:
    try:
        return node.md_path().read_text(encoding="utf-8")
    except OSError:  # includes FileNotFoundError raised by md_path() itself
        return None


def _open_annotation(text: str) -> ParsedAnnotation | None:
    return find_unclosed_cursor_annotation(text)


def _last_narrating_annotation(text: str) -> ParsedAnnotation | None:
    """The most recent narrating block in *text*, open or already closed.

    Scanning past closed blocks is the point: an inline ``play`` turn that has
    finished leaves ``[play] … [/play]`` with nothing open, and the honest
    answer to "what runs at this cursor" is still ``play``.
    """
    for segment in reversed(parse_segments(text)):
        ann = segment.annotation
        if ann is not None and ann.operator in NARRATING_OPERATOR_NAMES:
            return ann
    return None


def detect_open_session_operator(node: NarrativeNode) -> str | None:
    """The session operator whose *unclosed* annotation owns *node*.

    The session tag lives on the node that opened it, which is not always the
    immediate parent — opening a ``section`` inside a ``play`` session pushes
    the cursor a level deeper and the play tag stays on the grandparent — so
    walk the ancestors from nearest to root.

    ``None`` once the session closes, which is what callers gating ``--end``
    need: a finished session must not still offer to end itself.
    """
    for depth in range(len(node.key_path) - 1, -1, -1):
        ancestor = NarrativeNode(
            narrative_root=node.narrative_root, key_path=node.key_path[:depth]
        )
        ancestor_text = _node_text(ancestor)
        if ancestor_text is None:
            continue
        ann = _open_annotation(ancestor_text)
        if ann is not None and ann.operator in SESSION_OPERATOR_NAMES:
            return ann.operator
    return None


def detect_operator_name(node: NarrativeNode) -> str | None:
    """Return the operator whose prompt would be assembled at *node*.

    Three rules, most specific first:

    1. An open session on any ancestor owns the node
       (:func:`detect_open_session_operator`).
    2. Otherwise the node's own unclosed annotation names an operator that is
       still mid-flight.
    3. Otherwise the most recent *completed* narrating block decides.  Without
       this an inline ``play`` turn reports as ``write`` the moment it closes,
       which is the state a report is almost always read in.

    ``None`` when the node has no narrating history at all.
    """
    session_operator = detect_open_session_operator(node)
    if session_operator is not None:
        return session_operator

    text = _node_text(node)
    if text is None:
        return None

    own = _open_annotation(text)
    if own is not None:
        return own.operator

    recent = _last_narrating_annotation(text)
    return recent.operator if recent is not None else None
