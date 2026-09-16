"""Pending KB proposals: the ``[kb-op …]: #`` log, and the fold over it.

A ``design`` or ``advance`` session used to emit whole objects as fenced
``kb`` blocks that nothing applied until ``--end``.  Everything wrong with that
followed from the deferral rather than the format: a wrong object could not be
taken back, failures surfaced only at close, and every emitted body sat in
``[CURRENT PASSAGE]`` to be re-sent on every later turn.

Here the model calls a tool, and the call is persisted into the narrative node
as a **markdown comment** — one ``[kb-op …]: #`` block per call, appended in
call order.  Nothing is written to ``knowledge/`` during the session.  Instead
the cursor node's ops are folded into a :class:`PendingLayer` that
:class:`~lens.core.knowledge.KnowledgeStore` serves as one more precedence layer
above project-local, so every reader — crawl, ``kb get``, ``kb search``, the
command tools, the server — sees the same proposed reality.

Why a comment, and why the hyphen
---------------------------------
Exactly the :mod:`lens.core.llm_trace` trick, for the same reasons.
``ANNOTATION_RE`` requires ``[a-zA-Z_][a-zA-Z0-9_]*`` for the operator token, so
the hyphen in ``kb-op`` puts the block outside the annotation grammar and cursor
detection cannot mistake it for an open block — while
``strip_markdown_comments`` still removes it, because that works structurally on
comment blocks.  The name is ``kb-op`` and not ``kb-edit`` because ``kb_edit`` is
already the ``lens kb edit`` operator, whose claim tags live in ``knowledge/``
files; one underscore of difference would be a grep trap.

The blocks sit **inside** the operator's block (unlike the ``include``
annotations a module request earns, which go above the open tag), because
``write_discard`` truncates from the open tag down: a retried turn must leave no
KB trace at all.  ``rewind`` truncates them out with the node for the same
reason.  Git is not involved until the session closes.

Two hazards, both reproduced against this repo's own parsers
------------------------------------------------------------
1. A body line ending in ``]: #`` **closes the comment block early**, leaking the
   rest of the body plus an orphan terminator into the passage as visible prose.
2. A blank line inside the block stops it being a CommonMark link reference
   definition.  Lens' own ``strip_markdown_comments`` tolerates that, and so
   does the UI's structural stripper, but a plain markdown renderer would show
   the whole block.

:mod:`lens.core.llm_trace` answers both by dropping blank lines and appending a
marker, which is fine for telemetry and fatal here: a KB body has to materialize
**verbatim**.  So bodies are written into a YAML literal scalar behind a ``| ``
gutter — an empty source line becomes a non-blank ``|`` line, leading whitespace
is preserved exactly, and the block is obvious in a diff — and any line that
would still terminate the block early gets one trailing backslash, which the
reader strips.  The codec is bijective; see :func:`encode_body` /
:func:`decode_body`.

``render_kb_op`` additionally *asserts* the result is block-safe rather than
trusting the codec, because a leaked block is the one failure this channel must
not have, and it must fail loudly rather than quietly reach a reader.

Storage form
------------
Tool arguments are model text taking a new path to storage, so
``encode_ai_secrets_for_persist`` runs before encoding — the same conversion
``encode_patch_contents`` already makes for ``kb_patch``.  The overlay therefore
serves exactly what a file on disk would, which is what lets every existing
decode point (``format_objects_for_model``, the secret-decode transform) keep
working unchanged, and lets materialization write through with no second pass.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import yaml

__all__ = [
    "KB_OP_TAG",
    "KbOp",
    "KbOpError",
    "KbOpSink",
    "PendingBase",
    "PendingLayer",
    "assert_block_safe",
    "decode_body",
    "encode_body",
    "fold",
    "inflight_ops",
    "inflight_sink",
    "parse_kb_ops",
    "render_kb_op",
]

KB_OP_TAG = "kb-op"
"""Block token. Hyphenated so it stays outside the annotation grammar."""

KbVerb = Literal["add", "patch", "tag", "remove", "applied"]

_BLOCK_BREAKER = re.compile(r"\]:\s*#\s*$")
"""A line matching this ends the comment block — see the module docstring."""

_BLANK_LINE = re.compile(r"^[ \t]*$")

_INDENT = "  "
_BODY_INDENT = "    "
_GUTTER = "|"


# ---------------------------------------------------------------------------
# Body codec
# ---------------------------------------------------------------------------


def _defuse(line: str) -> str:
    """Append one backslash if *line* would terminate the block or be ambiguous.

    Both conditions are needed.  The breaker case is the hazard itself; the
    ``endswith("\\\\")`` case is what keeps the escape reversible, so a body line
    that genuinely ends in a backslash does not decode to one fewer.
    """
    if line.endswith("\\") or _BLOCK_BREAKER.search(line):
        return line + "\\"
    return line


def _undefuse(line: str) -> str:
    return line[:-1] if line.endswith("\\") else line


def encode_body(text: str) -> list[str]:
    """Gutter-encode *text* into lines safe inside a markdown comment block.

    Returned lines carry the ``|`` gutter but not the YAML indent, which the
    renderer adds.  An empty source line becomes a bare ``|``.
    """
    out: list[str] = []
    for line in text.split("\n"):
        gutter = _GUTTER if line == "" else f"{_GUTTER} {line}"
        out.append(_defuse(gutter))
    return out


def decode_body(lines: Sequence[str]) -> str:
    """Inverse of :func:`encode_body`. *lines* have the YAML indent removed."""
    out: list[str] = []
    for raw in lines:
        line = _undefuse(raw)
        if line == _GUTTER:
            out.append("")
        elif line.startswith(f"{_GUTTER} "):
            out.append(line[len(_GUTTER) + 1 :])
        else:
            # Not gutter-encoded: a hand-edited block.  Take it literally rather
            # than dropping it — a person fixing a proposal by hand should not
            # have to know the codec to delete a line.
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The op
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KbOp:
    """One proposal, or the ``applied`` marker that records a materialization.

    *line_start* / *line_end* are 1-based inclusive positions in the node the op
    was parsed from, and are ``0`` for an op that has not been parsed back yet.
    They exist so a person or a client can go and edit the exact block.
    """

    op: KbVerb
    id: str = ""
    body: str | None = None
    patches: tuple[dict[str, Any], ...] = ()
    tags: tuple[str, ...] = ()
    remove_tags: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    at: str = ""
    session: str = ""
    line_start: int = 0
    line_end: int = 0


@dataclass(frozen=True)
class KbOpError:
    """One op that did not resolve, and enough detail to go fix the block."""

    index: int
    op: KbVerb
    id: str
    reason: str
    line_start: int = 0
    line_end: int = 0

    def __str__(self) -> str:
        where = f" (node line {self.line_start})" if self.line_start else ""
        return f"kb-op #{self.index} {self.op} {self.id}{where}: {self.reason}"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


_PLAIN_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:/+-]*$")


def _scalar(value: str) -> str:
    """A one-line YAML scalar for *value*.

    Plain when it is obviously safe, so the common case stays readable, and
    ``json.dumps`` otherwise.  JSON strings are valid YAML double-quoted
    scalars and escape every newline, which is the property that matters: a
    scalar yaml would have folded across lines could put a blank line inside the
    block, and a blank line is one of the two ways this channel leaks.
    """
    if _PLAIN_SCALAR.match(value) and not _BLOCK_BREAKER.search(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def assert_block_safe(text: str) -> None:
    """Fail loudly if the rendered block would leak into the passage.

    Checks the **rendered lines**, not the pieces they were assembled from: a
    single field can carry an embedded newline, and a check over the pieces
    would not see it.  The codec is meant to make this unreachable; asserting it
    anyway is the difference between a bug that raises during a tool call and a
    bug that silently puts a KB body into the model's context for the rest of a
    session.
    """
    lines = text.split("\n")
    terminators = [i for i, line in enumerate(lines) if _BLOCK_BREAKER.search(line)]
    if not terminators:
        raise ValueError("kb-op block has no terminator")
    end = terminators[0]
    if end != len(lines) - 1 - (1 if lines[-1] == "" else 0):
        raise ValueError(
            f"kb-op block would terminate early at line {end}: {lines[end]!r}"
        )
    for i, line in enumerate(lines[:end]):
        if _BLANK_LINE.match(line):
            raise ValueError(f"kb-op block has a blank line at line {i}: {line!r}")


def render_kb_op(op: KbOp) -> str:
    """The ``[kb-op …]: #`` block for *op*, ending in a newline."""
    lines: list[str] = [f"[{KB_OP_TAG}"]
    add = lines.append
    add(f"{_INDENT}op: {op.op}")
    if op.id:
        add(f"{_INDENT}id: {op.id}")
    if op.at:
        add(f"{_INDENT}at: {op.at}")
    if op.session:
        add(f"{_INDENT}session: {_scalar(op.session)}")
    if op.body is not None:
        add(f"{_INDENT}body: |")
        for encoded in encode_body(op.body):
            add(f"{_BODY_INDENT}{encoded}")
    if op.patches:
        # Compact JSON on one line, not block YAML.  Patch targets and content
        # are arbitrary model text: a block scalar could contain a blank line or
        # a terminator, while ``json.dumps`` escapes every newline and JSON is
        # valid YAML flow syntax, so it reads straight back.
        add(f"{_INDENT}patches: {json.dumps(list(op.patches), ensure_ascii=False)}")
    for key, values in (("tags", op.tags), ("remove-tags", op.remove_tags),
                        ("ids", op.ids), ("removed", op.removed)):
        if values:
            add(f"{_INDENT}{key}:")
            for value in values:
                add(f"{_BODY_INDENT}- {_scalar(value)}")
    add("]: #")
    rendered = "\n".join(lines) + "\n"
    assert_block_safe(rendered)
    return rendered


def render_kb_ops(ops: Iterable[KbOp]) -> str:
    """Blocks for *ops*, separated by a blank line, or ``""`` for none.

    The blank line between blocks is outside every block, which is where
    markdown needs it: each reference-style comment must start its own block.
    """
    blocks = [render_kb_op(op).rstrip("\n") for op in ops]
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def iter_kb_op_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield ``(start, end_exclusive)`` 0-based line spans of ``[kb-op`` blocks.

    An unterminated block runs to end of text: everything from the opener on is
    proposal metadata, not prose, and treating the remainder as prose would put
    a KB body into the passage.
    """
    lines = text.split("\n")
    i = 0
    opener = f"[{KB_OP_TAG}"
    while i < len(lines):
        if lines[i].lstrip().startswith(opener):
            j = i
            while j < len(lines) and not _BLOCK_BREAKER.search(lines[j]):
                j += 1
            yield (i, min(j + 1, len(lines)))
            i = j + 1
            continue
        i += 1


def _decode_body_field(raw: str) -> str:
    """Decode a ``body: |`` literal scalar back to the original text.

    YAML's clip chomping appends exactly one newline to a literal block, so the
    final empty element is the scalar's terminator and not a body line.  A body
    that genuinely ends in a blank line still round-trips: :func:`encode_body`
    emitted a bare ``|`` line for it, which survives this trim.
    """
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return decode_body(lines)


def _op_from_mapping(data: dict[str, Any], start: int, end: int) -> KbOp | None:
    raw_op = data.get("op")
    if raw_op not in ("add", "patch", "tag", "remove", "applied"):
        return None
    verb: KbVerb = raw_op
    raw_id = data.get("id")
    body = data.get("body")
    patches_raw = data.get("patches")
    return KbOp(
        op=verb,
        id=str(raw_id).strip().lower() if isinstance(raw_id, str) else "",
        body=_decode_body_field(body) if isinstance(body, str) else None,
        patches=_patch_tuple(patches_raw),
        tags=_str_tuple(data.get("tags")),
        remove_tags=_str_tuple(data.get("remove-tags")),
        ids=_str_tuple(data.get("ids")),
        removed=_str_tuple(data.get("removed")),
        at=str(data.get("at", "")) if data.get("at") is not None else "",
        session=str(data.get("session", "")) if data.get("session") is not None else "",
        line_start=start + 1,
        line_end=end,
    )


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = cast(list[Any], value)
    return tuple(str(v) for v in items if v is not None)


def _patch_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    items = cast(list[Any], value)
    return tuple(cast(dict[str, Any], p) for p in items if isinstance(p, dict))


def parse_kb_ops(text: str) -> list[KbOp]:
    """Every ``[kb-op …]: #`` block in *text*, in document order.

    Document order is the fold's call order, which is the whole composition
    model: ops are an ordered log, not a set.  A block that does not parse is
    skipped rather than raised on — a hand-mangled block must not make the
    entire store unreadable — and the fold reports a broken *op*, which is the
    failure a person can act on.
    """
    lines = text.split("\n")
    ops: list[KbOp] = []
    for start, end in iter_kb_op_spans(text):
        inner = lines[start + 1 : end - 1]
        try:
            data = yaml.safe_load("\n".join(inner))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        op = _op_from_mapping(dict(data), start, end)  # pyright: ignore[reportUnknownArgumentType]
        if op is not None:
            ops.append(op)
    return ops


def split_kb_op_blocks(text: str) -> tuple[str, list[str]]:
    """Separate rendered ``[kb-op …]: #`` blocks out of *text*.

    The sibling of :func:`lens.core.llm_trace.split_trace_blocks`, and it exists
    for the same reason: any caller that *reshapes* composed output — quoting it
    into a summary, indenting it — takes the blocks with it, and a ``> [kb-op``
    line is no longer strippable, so the proposal reaches the model as prose.
    """
    lines = text.split("\n")
    spans = list(iter_kb_op_spans(text))
    if not spans:
        return text, []
    blocks: list[str] = []
    kept: list[str] = []
    cut: set[int] = set()
    for start, end in spans:
        blocks.append("\n".join(lines[start:end]).rstrip("\n") + "\n")
        cut.update(range(start, end))
    for i, line in enumerate(lines):
        if i not in cut:
            kept.append(line)
    return "\n".join(kept), blocks


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


class PendingBase(Protocol):
    """What the fold needs to know about the world underneath the proposals.

    Deliberately narrow, and deliberately *not*
    :class:`~lens.core.knowledge.KnowledgeStore`: the fold runs underneath the
    store's overlay-aware reads, so it must be handed the base view explicitly
    or it would consult itself.
    """

    def object_text(self, canonical_id: str) -> str | None:
        """Stored text, or ``None`` when the id resolves nowhere."""
        ...

    def object_tags(self, canonical_id: str) -> list[str]:
        """Stored tags, or ``[]``."""
        ...

    def exists_on_disk(self, canonical_id: str) -> bool:
        """Whether a file (project or dataset) holds this id."""
        ...


@dataclass
class PendingLayer:
    """The fold of an ops log: what the store should serve instead of disk.

    ``objects`` and ``tags`` hold only *touched* ids.  ``removed`` means "the
    project file goes away", not "the id is gone" — an id that also lives in a
    dataset falls back to the dataset, because that is what a fetch would return
    after the delete actually happened, and an overlay that predicts something
    other than the world it is standing in front of is worse than no overlay.
    """

    objects: dict[str, str] = field(default_factory=dict[str, str])
    tags: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    removed: set[str] = field(default_factory=set[str])
    created: set[str] = field(default_factory=set[str])
    errors: list[KbOpError] = field(default_factory=list[KbOpError])
    applied: list[KbOp] = field(default_factory=list[KbOp])

    def is_empty(self) -> bool:
        return not (self.objects or self.tags or self.removed or self.errors)

    def touched_ids(self) -> set[str]:
        return set(self.objects) | set(self.tags) | set(self.removed)


EMPTY_LAYER = PendingLayer()


def fold(ops: Sequence[KbOp], base: PendingBase) -> PendingLayer:
    """Replay *ops* over *base* and return what the store should serve.

    Recomputed from scratch on every read, which is what makes the whole design
    work: there is no incremental state to corrupt, no idempotency requirement,
    and a model that changes its mind just calls the next operation.  It also
    means the stack is **re-validated on every read** — a patch whose anchor a
    user has since hand-edited away turns into a :class:`KbOpError` the next
    time anything looks at the store, instead of at ``--end``.

    Composition, per verb: patches compose in call order, each re-resolving
    against the already-folded text; a second ``add`` replaces the first,
    because that is what a whole-body write means; ``remove`` then ``add``
    re-creates, ``add`` then ``remove`` leaves nothing; tag ops accumulate, with
    ``remove-tags`` applied after ``tags`` within one op.
    """
    from lens.core.text_select import SelectionError, apply_kb_patches

    layer = PendingLayer()

    def current_text(cid: str) -> str | None:
        if cid in layer.objects:
            return layer.objects[cid]
        if cid in layer.removed:
            return None
        return base.object_text(cid)

    def current_tags(cid: str) -> list[str]:
        if cid in layer.tags:
            return list(layer.tags[cid])
        if cid in layer.removed:
            return []
        return list(base.object_tags(cid))

    def fail(index: int, op: KbOp, reason: str) -> None:
        layer.errors.append(
            KbOpError(
                index=index,
                op=op.op,
                id=op.id,
                reason=reason,
                line_start=op.line_start,
                line_end=op.line_end,
            )
        )

    for index, op in enumerate(ops, start=1):
        if op.op == "applied":
            layer.applied.append(op)
            continue
        if not op.id:
            fail(index, op, "missing id")
            continue

        if op.op == "add":
            if op.body is None:
                fail(index, op, "add requires a body")
                continue
            layer.removed.discard(op.id)
            layer.objects[op.id] = op.body
            if not base.exists_on_disk(op.id):
                layer.created.add(op.id)
            continue

        if op.op == "patch":
            text = current_text(op.id)
            if text is None:
                fail(index, op, f"{op.id} does not exist, so there is nothing to patch")
                continue
            try:
                new_text, _kind = apply_kb_patches(
                    text, list(op.patches), source_id=f"kb-op:{op.id}"
                )
            except SelectionError as e:
                fail(index, op, str(e))
                continue
            layer.objects[op.id] = new_text
            continue

        if op.op == "tag":
            if current_text(op.id) is None:
                fail(index, op, f"{op.id} does not exist, so there is nothing to tag")
                continue
            tags = current_tags(op.id)
            for tag in op.tags:
                if tag not in tags:
                    tags.append(tag)
            for tag in op.remove_tags:
                if tag in tags:
                    tags.remove(tag)
            layer.tags[op.id] = tags
            continue

        if op.op == "remove":
            if current_text(op.id) is None:
                fail(index, op, f"{op.id} does not exist, so there is nothing to remove")
                continue
            if op.id in layer.created:
                # Created and dropped inside this session: nothing was ever
                # written, so there is nothing to delete at materialization.
                layer.objects.pop(op.id, None)
                layer.tags.pop(op.id, None)
                layer.created.discard(op.id)
                continue
            layer.objects.pop(op.id, None)
            layer.tags.pop(op.id, None)
            layer.removed.add(op.id)

    return layer


# ---------------------------------------------------------------------------
# In-flight ops
# ---------------------------------------------------------------------------


@dataclass
class KbOpSink:
    """Ops the model proposed during one generation, before anything persists.

    Read by the store while the generation is still running, so a ``kb_get``
    after a ``kb_add`` in the same turn sees the new object.  ``revision`` is
    the cache key that makes that visible without a timestamp.
    """

    ops: list[KbOp] = field(default_factory=list[KbOp])
    revision: int = 0

    def record(self, op: KbOp) -> None:
        self.ops.append(op)
        self.revision += 1


_INFLIGHT: dict[Path, KbOpSink] = {}
"""Per-project in-flight sinks, scoped by :func:`inflight_ops`.

A process-scoped registry rather than a parameter threaded through the ~70
``KnowledgeStore.for_project`` / ``session.kb`` call sites — and more to the
point, threading would only reach the handlers someone remembered to thread, so
a modality tool or a dataset-extension tool would silently read stale reality,
which is the exact failure this system exists to remove.  Keyed by resolved
project root; the server already serialises to one stream per project.
"""


@contextmanager
def inflight_ops(project_root: Path, sink: KbOpSink) -> Generator[None]:
    """Make *sink*'s ops visible to every read of *project_root* inside the block."""
    key = project_root.resolve()
    previous = _INFLIGHT.get(key)
    _INFLIGHT[key] = sink
    try:
        yield
    finally:
        if previous is None:
            _INFLIGHT.pop(key, None)
        else:
            _INFLIGHT[key] = previous


def inflight_sink(project_root: Path) -> KbOpSink | None:
    """The sink currently scoped to *project_root*, if a generation is running."""
    return _INFLIGHT.get(project_root.resolve())
