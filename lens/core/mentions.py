"""Mentions and includes: KB scope added mid-node that expands in place.

Three scopes put a KB object in context, told apart by **where they were
written**, not by what they mean:

============================  ======================  ==========================
Scope                         Written                 Lifetime
============================  ======================  ==========================
node pin (``kb_pin``)         node front matter       whole node, inherited
``include``                   annotation mid-node     rest of the node
``mention``                   annotation mid-node     one assistant turn
============================  ======================  ==========================

Includes and mentions render **in place** — at the line where they were added —
rather than in ``[RELEVANT KNOWLEDGE]``.  With multi-turn assembly the cacheable
prefix ends at the previous turn, so the knowledge block is the worst place for
anything that changes per beat: adding one mention there re-writes the whole
prompt including the transcript.  Expanding at the mention's own line is
append-only, and it binds the reference to the line that motivated it.

Lifetime is **computed from distance to the cursor**, never stored and never
decremented (see :func:`live_mentions`).  Consequences worth preserving:

*  retry does not consume a mention (there is no counter to consume);
*  rewinding past an expiry restores it, because the annotation is still in the
   text and only the render decision changed;
*  two clients rendering the same node agree, and nothing drifts from git.

Do **not** "clean up" expired annotations — their persistence is what makes
rewind work.  Nothing is ever physically written into the node either:
:func:`render_mentions_in_place` returns a throwaway buffer used for one prompt.
Physical expansion (tried once, do not repeat) bloats the file permanently,
snapshots KB content that later drifts from the object, and destroys rewind.

Annotation form is a single-line markdown reference comment carrying one id::

    [mention: spell.aid]: #
    [include: rules.grappling]: #

which :func:`~lens.core.annotations.parse_annotations` deliberately does not
recognise (see ``ANNOTATION_RE``), so these are inert comments to the rest of
the system: stripped from LLM-visible text, invisible to cursor detection, and
excluded from auto-compress byte accounting.  Operators whose prompt lives in
their own annotation params (``write``, ``chat``, ``design``) record the same
thing as ``mention:`` / ``include:`` list params instead — see
:func:`parse_mentions`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lens.core.annotations import MENTION_LINE_RE, parse_annotations
from lens.core.crawl_transforms import is_state_tags
from lens.core.knowledge import KnowledgeStore
from lens.core.storage import Storage
from lens.core.turns import build_annotation_intervals

MentionKind = Literal["mention", "include"]

MENTION = "mention"
INCLUDE = "include"

MENTION_KINDS: tuple[MentionKind, ...] = (MENTION, INCLUDE)
"""Annotation names, and the operator param keys that carry the same thing."""

__all__ = [
    "INCLUDE",
    "MENTION",
    "MENTION_KINDS",
    "MENTION_LINE_RE",
    "MentionExpansion",
    "MentionKind",
    "MentionRef",
    "append_mention_annotations",
    "build_mention_annotations",
    "live_mentions",
    "parse_mentions",
    "render_mentions_in_place",
]


@dataclass(frozen=True)
class MentionExpansion:
    """One block that :func:`render_mentions_in_place` actually emitted.

    Reported back because the expansion is spliced *into* the passage rather
    than added as its own component, so nothing downstream could otherwise tell
    that a mention took effect — and answering exactly that is what ``lens
    explain`` is for.
    """

    kind: MentionKind
    kb_id: str
    bytes: int
    text: str
    """The block exactly as spliced in, so a reader of the finished passage can
    find it again and account for its bytes separately."""


@dataclass(frozen=True)
class MentionRef:
    """One mention or include, and the disk line it renders at."""

    kind: MentionKind
    kb_id: str
    line: int
    """1-based disk line the block renders before.  For a standalone annotation,
    its own line; for a ``mention:`` param, the operator's open tag line."""


def build_mention_annotations(kind: MentionKind, ids: Sequence[str]) -> str:
    """Render one annotation line per distinct id, in first-occurrence order.

    A message naming several objects (``I cast @spell.aid on @pc.rowan``) writes
    one line each; the same id twice writes one line.  Returns ``""`` for no ids.
    """
    lines = [f"[{kind}: {kid}]: #" for kid in _dedup(ids)]
    return "\n".join(lines)


def append_mention_annotations(
    text: str, scoped: Mapping[str, Sequence[str]]
) -> str:
    """Append *scoped* annotations to *text* as their own markdown block.

    Every caller that writes these into a node must go through here.  A
    reference-style comment only disappears from the rendered page when it
    **starts** a block: written straight under a line of prose it is a lazy
    continuation of that paragraph, and the reader sees ``[mention: spell.aid]: #``
    sitting in the story — the exact machinery annotations exist to hide.  The
    separator logic mirrors :meth:`~lens.core.operator.Operator.append_to_node`,
    and the trailing newline keeps whatever is appended next safe too.

    *scoped* is the mapping :meth:`~lens.core.operator.Operator.mention_params`
    returns; kinds are emitted in :data:`MENTION_KINDS` order.
    """
    lines = "\n".join(
        block
        for kind in MENTION_KINDS
        if (block := build_mention_annotations(kind, scoped.get(kind) or []))
    )
    if not lines:
        return text
    if not text:
        return lines + "\n"
    if text.endswith("\n\n"):
        sep = ""
    elif text.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return text + sep + lines + "\n"


def _dedup(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for kid in ids:
        cleaned = kid.strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        out.append(cleaned)
    return out


def _param_ids(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]  # pyright: ignore[reportUnknownVariableType]
    return []


def parse_mentions(raw: str) -> list[MentionRef]:
    """Every mention/include written into *raw*, ordered by line.

    Two sources, because there are two places a mention can be written:

    1.  standalone ``[mention: id]: #`` / ``[include: id]: #`` comment lines,
        which is what ``play`` appends next to the player's line;
    2.  ``mention:`` / ``include:`` params on an operator annotation, for
        operators whose prompt is not in the prose (``write``, ``chat``,
        ``design``) — the annotation itself is then the position, so the block
        lands immediately before the content it motivated.
    """
    refs: list[MentionRef] = []

    for index, line in enumerate(raw.split("\n")):
        match = MENTION_LINE_RE.match(line)
        if match is None:
            continue
        kind: MentionKind = "include" if match.group("kind") == "include" else "mention"
        refs.append(MentionRef(kind=kind, kb_id=match.group("id"), line=index + 1))

    for ann in parse_annotations(raw):
        if ann.closing:
            continue
        for kind_key in MENTION_KINDS:
            for kid in _param_ids(ann.params.get(kind_key)):
                refs.append(
                    MentionRef(kind=kind_key, kb_id=kid, line=ann.line_start)
                )

    refs.sort(key=lambda ref: ref.line)
    return refs


def live_mentions(raw: str) -> list[MentionRef]:
    """The subset of :func:`parse_mentions` still expanding at the cursor.

    An ``include`` never expires.  A ``mention`` is live until an assistant turn
    *starts* after it — one turn, counted rather than stored, so there is nothing
    to decrement, consume on retry, or drift out of sync with git.
    """
    refs = parse_mentions(raw)
    if not refs:
        return []
    assistant_starts = [
        start
        for start, _, role in build_annotation_intervals(parse_annotations(raw))
        if role == "assistant"
    ]
    return [
        ref
        for ref in refs
        if ref.kind == "include"
        or not any(start > ref.line for start in assistant_starts)
    ]


def render_mentions_in_place(
    raw: str,
    *,
    project_root: Path,
    storage: Storage,
    pinned_ids: Iterable[str] = (),
    pending: Sequence[MentionRef] = (),
) -> tuple[str, list[str], list[MentionExpansion]]:
    """Return *raw* expanded, ids deferred to the tail, and what was emitted.

    The expansion is the canonical ``KB['type.key']`` block from
    :meth:`~lens.core.storage.Storage.format_kb_prompt_block` — the same shape
    the pinned path emits, so the model never learns a second format and inline
    reference text cannot be mistaken for narration.

    The result is a throwaway buffer, never written to disk.  It is fed back
    through ``normalize_raw_text`` by callers, so annotation line numbers and
    the disk-line map both describe the *expanded* text and stay consistent for
    :func:`~lens.core.turns.parse_passage_turns`.

    *pending* covers the one turn where the annotation is not on disk yet: a
    fresh inline generation persists its annotation only after the model
    answers.  Pending refs render at end-of-text, which is byte-identical to
    where the persisted annotation lands, so the next beat reads it off disk
    with no cache churn.

    Suppression, in order: already pinned (it is in ``[RELEVANT KNOWLEDGE]``
    already), already rendered in place and still live (keeps the buffer
    append-only stable while still letting an expired mention be refreshed), and
    tagged ``state`` — those are returned as the second element instead, for the
    caller to add as components so ``_divert_state_components`` can put them in
    ``[LIVE STATE]``.  A mutable object inlined into the transcript would freeze
    a snapshot in the cacheable prefix, which is exactly what tagging it
    ``state`` asks Lens not to do.
    """
    refs = [*live_mentions(raw), *pending]
    if not refs:
        return raw, [], []

    lines = raw.split("\n")
    end_line = len(lines) + 1
    kb = KnowledgeStore.for_project(project_root)
    suppressed = {kid.rstrip("+").lower() for kid in pinned_ids}
    rendered: set[str] = set()
    state_ids: list[str] = []
    expansions: list[MentionExpansion] = []
    # 1-based line -> blocks to emit immediately before it.  The annotation
    # itself stays put: it is a markdown comment, so it strips out downstream
    # either way, and leaving it keeps the buffer a superset of the real file.
    inserts: dict[int, list[str]] = {}

    for ref in refs:
        objects = kb.get_objects([ref.kb_id])
        obj = objects.get(ref.kb_id.lower()) or objects.get(ref.kb_id)
        if obj is None:
            continue
        if obj.id.lower() in suppressed or obj.id.lower() in rendered:
            continue
        rendered.add(obj.id.lower())
        if is_state_tags(obj.tags):
            state_ids.append(obj.id)
            continue
        block = storage.format_kb_prompt_block(
            canonical_id=obj.id,
            text=obj.text,
            tags=obj.tags,
            include_comments=False,
            source_id=f"mention:{obj.id}",
        )
        line = ref.line if ref.line <= len(lines) else end_line
        inserts.setdefault(line, []).append(block)
        emitted = block.rstrip("\n")
        expansions.append(
            MentionExpansion(
                kind=ref.kind,
                kb_id=obj.id,
                bytes=len(emitted.encode("utf-8")),
                text=emitted,
            )
        )

    if not inserts:
        return raw, state_ids, expansions

    def emit(block: str) -> None:
        # Blank line on both sides, so the block reads as its own unit rather
        # than running into the sentence that motivated it.
        if out and out[-1] != "":
            out.append("")
        out.extend(block.rstrip("\n").split("\n"))
        out.append("")

    out: list[str] = []
    for index, line in enumerate(lines, start=1):
        for block in inserts.get(index, ()):
            emit(block)
        out.append(line)
    for block in inserts.get(end_line, ()):
        emit(block)
    return "\n".join(out), state_ids, expansions
