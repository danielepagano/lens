"""Triggers: prep-declared suggestions to run a session operator (#195).

Prep holds parts back on purpose — a part that may never come up, or one whose
shape depends on the state at that moment.  A **trigger** is the stored
suggestion to build or play that part when its moment arrives:

```
[
    triggers:
      design-cellar:
        when: Enso enters the store cellar
        run: design --module encounter --pin prep.village-store "design the cellar encounter"
]: #
```

It lives in a KB object's front matter, which is a markdown comment, so the
crawl and ``kb_headline`` already strip it and the ``run`` never reaches the
play model.  Operators write it through the ``kb_set_trigger`` verb; people may
edit it by hand.

**Its slug names the node it creates**, ``<slug>-tr``, and that node existing
anywhere in the active narrative is what "done" means.  Nothing else tracks
state: detection is one directory walk over *names* (:func:`fired_slugs`), no
file is opened, collate keeps names when it moves a node, and rewind/rollback
delete it so the trigger reopens for free.  The ``-tr`` suffix is reserved —
only firing a trigger may create such a node.

A slug always starts with its operator (``design-cellar``, ``play-cellar``), so
designing and playing the same part never collide.

The play model is shown the open triggers in a tail ``[HELD BACK]`` block and
emits ``<!-- suggest:<slug> -->`` when it reaches one.  An **offer** is such a
marker in the cursor's current passage whose trigger is still open
(:func:`open_offers`); the CLI and UI turn it into a "run it?" prompt.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from lens.core.annotations import (
    parse_annotations,
    parse_front_matter,
    set_front_matter_key,
    strip_html_comments,
    strip_markdown_comments,
)
from lens.core.exceptions import ValidationError

if TYPE_CHECKING:
    from lens.core.knowledge import KnowledgeStore
    from lens.core.narrative import NarrativeNode

__all__ = [
    "ADVANCE_OFFER_SLUG",
    "TRIGGERS_KEY",
    "TRIGGER_NODE_SUFFIX",
    "Trigger",
    "TriggerError",
    "TriggerInvocation",
    "TriggerOrigin",
    "declared_triggers",
    "fired_slugs",
    "normalize_trigger_slug",
    "open_offers",
    "parse_trigger_run",
    "pins_at_or_above",
    "render_suggest",
    "session_trigger",
    "suggested_slugs",
    "trigger_node_name",
    "triggers_from_text",
    "with_trigger",
]

TRIGGERS_KEY = "triggers"
"""Front-matter key holding the ``slug -> {when, run}`` map."""

TRIGGER_NODE_SUFFIX = "-tr"
"""Reserved node-name suffix: ``<slug>-tr`` is the node firing *slug* creates."""

ANN_TRIGGER = "trigger"
ANN_TRIGGER_FROM = "trigger_from"
ANN_TRIGGER_WHEN = "when"
"""Params written onto a session's open annotation when a trigger opened it."""

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

SUGGEST_RE = re.compile(r"<!--\s*suggest:\s*([a-z0-9][a-z0-9_-]*)\s*-->")
"""The marker the play model (or a session close) writes to offer a trigger."""


ADVANCE_OFFER_SLUG = "advance"
"""The one built-in offer: ``<!-- suggest:advance -->``, written by play at a time skip.

Not a trigger.  Nothing declares it, firing it runs ``advance`` (which names its
own ``advance-day-*`` node, never a ``-tr`` one), and it recurs every night, so
"done" cannot be a node name.  It is live only while the marker is still the
last thing in the passage (:func:`_advance_offer`).  A declared slug always
carries a hyphen after its operator, so it can never collide with this one.
"""

ADVANCE_OFFER_WHEN = "the fiction has reached a time skip"


class TriggerError(ValidationError):
    """A slug, ``run`` or trigger lookup that cannot be honoured."""


@dataclass(frozen=True)
class Trigger:
    """One declared trigger and the KB object that declares it."""

    slug: str
    when: str
    run: str
    declared_on: str
    kind: str = "trigger"
    """``"trigger"`` for a declared one; ``"advance"`` for the built-in offer,
    which clients must not tag as a trigger (it opens no ``-tr`` session)."""

    @property
    def operator(self) -> str:
        return self.slug.split("-", 1)[0]

    def as_dict(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "when": self.when,
            "run": self.run,
            "declared_on": self.declared_on,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class TriggerOrigin:
    """What opened a session: read back off its open annotation."""

    slug: str
    when: str
    declared_on: str


@dataclass
class TriggerInvocation:
    """A parsed ``run`` — what to call the session operator with."""

    operator: str
    prompt: str | None = None
    module_ids: list[str] = field(default_factory=list[str])
    pins: list[str] = field(default_factory=list[str])
    unpins: list[str] = field(default_factory=list[str])
    mentions: list[str] = field(default_factory=list[str])
    includes: list[str] = field(default_factory=list[str])
    llm_id: str | None = None
    reasoning: str | None = None
    do_pass: bool = False
    """``play --pass``: have the GM narrate.  Defaults on for a prompt-less play
    run, since a fired play session with no player line and no GM pass would
    open and say nothing."""


# ---------------------------------------------------------------------------
# Slugs and names
# ---------------------------------------------------------------------------


def trigger_node_name(slug: str) -> str:
    return f"{slug}{TRIGGER_NODE_SUFFIX}"


def is_reserved_node_name(name: str) -> bool:
    """True for a name only firing a trigger may create."""
    return name.endswith(TRIGGER_NODE_SUFFIX)


def normalize_trigger_slug(slug: str, operator: str) -> str:
    """Canonical slug for *operator*: prefix added when missing, rest validated.

    Mirrors ``--slug``: a bare ``cellar`` becomes ``design-cellar``.  A slug that
    already carries a *different* known operator prefix is rejected rather than
    double-prefixed, because ``design-play-cellar`` is never what was meant.
    """
    raw = (slug or "").strip().lower()
    if not raw:
        raise TriggerError("a trigger needs a slug")
    prefix = f"{operator}-"
    if not raw.startswith(prefix):
        head = raw.split("-", 1)[0]
        if "-" in raw and head in _session_operator_names() and head != operator:
            raise TriggerError(
                f"slug '{raw}' starts with '{head}-' but the trigger runs "
                f"'{operator}'; a slug always starts with its own operator"
            )
        raw = prefix + raw
    if not _SLUG_RE.fullmatch(raw) or raw == prefix.rstrip("-"):
        raise TriggerError(
            f"invalid trigger slug '{raw}' (lowercase letters, digits, '-' and '_')"
        )
    if is_reserved_node_name(raw):
        raise TriggerError(
            f"slug '{raw}' ends in '{TRIGGER_NODE_SUFFIX}', which is reserved for "
            "the node a trigger creates"
        )
    return raw


def _session_operator_names() -> frozenset[str]:
    return frozenset({"play", "design", "section", "chat", "advance"})


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def _raw_trigger_map(text: str) -> dict[str, Any]:
    raw = parse_front_matter(text).get(TRIGGERS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in cast(dict[Any, Any], raw).items()}


def triggers_from_text(text: str, declared_on: str) -> dict[str, Trigger]:
    """The ``triggers:`` map in *text*'s front matter.

    Tolerant by design: a hand-edited entry missing ``run`` or ``when`` is
    skipped, never raised on, because one broken trigger must not make the
    object — or a play turn that has it in scope — unreadable.
    """
    if TRIGGERS_KEY not in text:
        return {}
    out: dict[str, Trigger] = {}
    for slug, entry in _raw_trigger_map(text).items():
        if not isinstance(entry, dict):
            continue
        data = cast(dict[str, Any], entry)
        when = data.get("when")
        run = data.get("run")
        if not isinstance(when, str) or not isinstance(run, str):
            continue
        if not when.strip() or not run.strip():
            continue
        key = slug.strip().lower()
        out[key] = Trigger(
            slug=key, when=when.strip(), run=run.strip(), declared_on=declared_on
        )
    return out


def with_trigger(text: str, slug: str, when: str, run: str) -> str:
    """Upsert *slug* into *text*'s ``triggers:`` front matter; empty *run* removes it."""
    current = _raw_trigger_map(text)
    if run.strip():
        current[slug] = {"when": when.strip(), "run": run.strip()}
    else:
        current.pop(slug, None)
    return set_front_matter_key(text, TRIGGERS_KEY, current or None)


TRIGGERS_METADATA_KEY = "triggers"
"""Crawl-component metadata key carrying an object's ``{slug: when}`` as JSON."""


def kb_trigger_metadata(text: str) -> dict[str, str]:
    """Component metadata for a KB object's triggers, or ``{}`` for none.

    Carried the way ``tags`` is, so the render-time held-back pass reads it off
    components already in memory and a turn costs no extra file reads.  Only
    ``when`` travels: the ``run`` is for the CLI and UI, never for a model.
    """
    found = triggers_from_text(text, "")
    if not found:
        return {}
    payload = {slug: trig.when for slug, trig in found.items()}
    return {TRIGGERS_METADATA_KEY: json.dumps(payload, ensure_ascii=False)}


def triggers_from_metadata(value: str | None) -> dict[str, str]:
    """Inverse of :func:`kb_trigger_metadata`'s value; malformed input is ``{}``."""
    if not value:
        return {}
    try:
        data = json.loads(value)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    items = cast(dict[Any, Any], data).items()
    return {str(k): str(v) for k, v in items if isinstance(v, str)}


# ---------------------------------------------------------------------------
# Done: the narrative tree
# ---------------------------------------------------------------------------


def fired_slugs(narrative_root: Path) -> set[str]:
    """Slugs whose ``<slug>-tr`` node exists anywhere under *narrative_root*.

    Names only — no file is opened.  ``*-tr.md`` leaves and ``*-tr/`` folders
    both count; ``collate`` moves a node into a section but keeps its name, so a
    fired trigger stays found.
    """
    out: set[str] = set()
    if not narrative_root.is_dir():
        return out
    suffix = TRIGGER_NODE_SUFFIX
    for _dirpath, dirnames, filenames in os.walk(narrative_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in dirnames:
            if name.endswith(suffix):
                out.add(name[: -len(suffix)])
        for name in filenames:
            if name.endswith(f"{suffix}.md"):
                out.add(name[: -len(f"{suffix}.md")])
    return out


# ---------------------------------------------------------------------------
# Declarations across the store
# ---------------------------------------------------------------------------


def declared_triggers(kb: KnowledgeStore) -> dict[str, Trigger]:
    """Every trigger declared anywhere in *kb*, keyed by slug.

    Read through the store's overlay, so a ``kb_set_trigger`` earlier in the
    same design session counts.  Bodies are read only when the file mentions
    ``triggers:`` at all; this runs on design-time checks and on the offer
    lookup, never on the crawl.  On a duplicate slug (only reachable by hand
    editing — the verb refuses it) the first id in sorted order wins.
    """
    layer = kb.pending_layer()
    out: dict[str, Trigger] = {}
    index = kb.resolved_index()
    for cid in sorted(index):
        if cid in layer.objects:
            text = layer.objects[cid]
        else:
            try:
                text = index[cid].path.read_text(encoding="utf-8")
            except OSError:
                continue
        if TRIGGERS_KEY not in text:
            continue
        for slug, trig in triggers_from_text(text, cid).items():
            out.setdefault(slug, trig)
    return out


# ---------------------------------------------------------------------------
# Suggestions and offers
# ---------------------------------------------------------------------------


def render_suggest(slug: str) -> str:
    return f"<!-- suggest:{slug} -->"


def suggested_slugs(text: str) -> list[str]:
    """Distinct slugs suggested in *text*, in first-appearance order."""
    seen: list[str] = []
    for m in SUGGEST_RE.finditer(text):
        slug = m.group(1)
        if slug not in seen:
            seen.append(slug)
    return seen


def open_offers(kb: KnowledgeStore, narrative: NarrativeNode) -> list[Trigger]:
    """Offers at the cursor: suggested in its passage, declared, and still open.

    Unknown or done slugs simply do not show.  A marker that collate moved into
    a section is no longer in the current passage, so it stops being an offer.
    """
    try:
        cursor = narrative.find_cursor()
        text = cursor.md_path().read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return []
    slugs = suggested_slugs(text)
    if not slugs:
        return []
    out: list[Trigger] = []
    declared_slugs = [s for s in slugs if s != ADVANCE_OFFER_SLUG]
    if declared_slugs:
        declared = declared_triggers(kb)
        fired = fired_slugs(narrative.narrative_root)
        out = [declared[s] for s in declared_slugs if s in declared and s not in fired]
    if ADVANCE_OFFER_SLUG in slugs:
        advance = _advance_offer(cursor, text)
        if advance is not None:
            out.append(advance)
    return out


def _advance_offer(cursor: NarrativeNode, text: str) -> Trigger | None:
    """The built-in ``advance`` offer, if its marker is still live at *cursor*.

    Live means nothing has happened since the marker: after the last one there
    is no prose (a player line, a GM reply) and no opening annotation (an
    ``advance`` that ran, a new play block).  A closing tag is fine — play's own
    ``[/play]: #`` lands after the reply.  And a timeline must be in scope,
    because ``advance`` refuses to run without one.
    """
    last = None
    for m in SUGGEST_RE.finditer(text):
        if m.group(1) == ADVANCE_OFFER_SLUG:
            last = m
    if last is None:
        return None
    tail = text[last.end():]
    if strip_markdown_comments(strip_html_comments(tail)).strip():
        return None
    if any(not ann.closing for ann in parse_annotations(tail)):
        return None
    if not any(pid.startswith("timeline.") for pid in ids_in_scope_at(cursor)):
        return None
    return Trigger(
        slug=ADVANCE_OFFER_SLUG,
        when=ADVANCE_OFFER_WHEN,
        run="advance",
        declared_on="",
        kind="advance",
    )


def open_triggers(kb: KnowledgeStore, narrative: NarrativeNode) -> list[Trigger]:
    """Every declared trigger not yet fired in *narrative*, by slug."""
    fired = fired_slugs(narrative.narrative_root)
    return [t for s, t in sorted(declared_triggers(kb).items()) if s not in fired]


# ---------------------------------------------------------------------------
# Session origin and scope
# ---------------------------------------------------------------------------


def _parent_of(node: NarrativeNode) -> NarrativeNode | None:
    from lens.core.narrative import NarrativeNode

    if not node.key_path:
        return None
    return NarrativeNode(
        narrative_root=node.narrative_root, key_path=node.key_path[:-1]
    )


def session_trigger(
    node: NarrativeNode, operator_name: str | None = None
) -> TriggerOrigin | None:
    """The trigger that opened the session *node* is the sub-node of, if any.

    Read off the parent's ``[<op>:<id>]`` open annotation, the same place
    :func:`~lens.core.context.session_module_ids` reads modules from.  When
    *operator_name* is given the annotation must be that operator's.
    """
    parent = _parent_of(node)
    if parent is None or not parent.exists():
        return None
    session_id = node.key_path[-1]
    try:
        text = parent.md_path().read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return None
    for ann in reversed(parse_annotations(text)):
        if ann.id != session_id or ann.closing or ann.self_closing:
            continue
        if operator_name is not None and ann.operator != operator_name:
            return None
        slug = ann.params.get(ANN_TRIGGER)
        if not isinstance(slug, str) or not slug:
            return None
        when = ann.params.get(ANN_TRIGGER_WHEN)
        origin = ann.params.get(ANN_TRIGGER_FROM)
        return TriggerOrigin(
            slug=slug,
            when=str(when) if when is not None else "",
            declared_on=str(origin) if origin is not None else "",
        )
    return None


def cursor_session_trigger(project_root: Path) -> TriggerOrigin | None:
    """:func:`session_trigger` for the active narrative's cursor."""
    from lens.core.project import get_active_narrative

    try:
        narrative = get_active_narrative(project_root)
        if narrative is None or not narrative.exists():
            return None
        return session_trigger(narrative.find_cursor())
    except (OSError, ValueError, FileNotFoundError):
        return None


def pins_at_or_above(node: NarrativeNode) -> set[str]:
    """``kb_pin`` bases from *node*'s front matter and every ancestor's.

    A front-matter walk only — no ``+`` expansion, no modules — which is what
    "pinned at or above" means for a suggestion's declaring object.
    """
    from lens.core.narrative import NarrativeNode
    from lens.core.pinning import KB_PIN

    out: set[str] = set()
    for depth in range(len(node.key_path) + 1):
        level = NarrativeNode(
            narrative_root=node.narrative_root, key_path=node.key_path[:depth]
        )
        try:
            fm = level.front_matter()
        except (OSError, FileNotFoundError):
            continue
        raw = fm.get(KB_PIN)
        items: Iterable[Any] = (
            cast(list[Any], raw) if isinstance(raw, list) else ([raw] if raw else [])
        )
        for item in items:
            if isinstance(item, str) and item.strip():
                out.add(item.strip().rstrip("+").lower())
    return out


def ids_in_scope_at(node: NarrativeNode) -> set[str]:
    """KB ids a turn at *node* has in scope: pins, ``+`` expansions, facets.

    The same crawl ``lens stats`` reports as the effective pins, so the
    suggestion check agrees with what play actually renders. Play gathers
    triggers from every object in scope, including one a ``location.x+`` pin
    pulls in, and a check that only read front-matter pins would refuse exactly
    the hub pattern prep is encouraged to use. Falls back to the front-matter
    walk if the crawl cannot run.
    """
    from lens.core.context import CrawlSpec, crawl

    try:
        result = crawl(CrawlSpec.of(node, include_narrative=False))
    except Exception:  # noqa: BLE001 — a scope check must never break a close
        return pins_at_or_above(node)
    return {pid.rstrip("+").lower() for pid in result.pinned_ids} | pins_at_or_above(node)


def session_parent(project_root: Path) -> NarrativeNode | None:
    """Parent of the cursor node — where a session's close writes its offers."""
    from lens.core.project import get_active_narrative

    try:
        narrative = get_active_narrative(project_root)
        if narrative is None or not narrative.exists():
            return None
        return _parent_of(narrative.find_cursor())
    except (OSError, ValueError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Running: the stored ``run``
# ---------------------------------------------------------------------------

_LIST_FLAGS: Mapping[str, str] = {
    "--module": "module_ids",
    "-m": "module_ids",
    "--pin": "pins",
    "--unpin": "unpins",
    "--mention": "mentions",
    "--include": "includes",
}
_SCALAR_FLAGS: Mapping[str, str] = {
    "--llm": "llm_id",
    "-l": "llm_id",
    "--reasoning": "reasoning",
}
_REFUSED_FLAGS = frozenset({"--slug", "-s", "--end", "--retry", "-r"})


def fireable_operator_names() -> frozenset[str]:
    """Operators a trigger may run: the session operators that nest a sub-node."""
    from lens.core.operators import get_operator_class_for_name
    from lens.core.operators.session import SessionOperator

    out: set[str] = set()
    for name in ("design", "play"):
        cls = get_operator_class_for_name(name)
        if cls is not None and issubclass(cls, SessionOperator):
            out.add(name)
    return frozenset(out)


def parse_trigger_run(run: str) -> TriggerInvocation:
    """Parse a stored ``run`` into a :class:`TriggerInvocation`.

    The grammar is a subset of the operator's own CLI: the operator name, then
    ``--module/-m``, ``--pin``, ``--unpin``, ``--mention``, ``--include``,
    ``--llm/-l``, ``--reasoning`` and a prompt.  Session-shaping flags
    (``--slug``, ``--end``, ``--retry``) are refused, because firing a trigger
    names the session itself and always opens a fresh one.
    """
    try:
        tokens = shlex.split(run or "")
    except ValueError as e:
        raise TriggerError(f"cannot parse run: {e}") from e
    if tokens and tokens[0] == "lens":
        tokens = tokens[1:]
    if not tokens:
        raise TriggerError("run is empty")
    operator = tokens[0]
    allowed = fireable_operator_names()
    if operator not in allowed:
        raise TriggerError(
            f"run must start with a session operator ({', '.join(sorted(allowed))}); "
            f"got '{operator}'"
        )
    inv = TriggerInvocation(operator=operator)
    prompt_parts: list[str] = []
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        flag, eq, inline = tok.partition("=")
        if tok == "--pass":
            if operator != "play":
                raise TriggerError("--pass only applies to play")
            inv.do_pass = True
            i += 1
            continue
        if flag in _REFUSED_FLAGS:
            raise TriggerError(
                f"run may not use {flag}: firing a trigger names and opens the session"
            )
        if flag in _LIST_FLAGS or flag in _SCALAR_FLAGS:
            if eq:
                value = inline
            else:
                i += 1
                if i >= len(tokens):
                    raise TriggerError(f"{flag} needs a value")
                value = tokens[i]
            if flag in _LIST_FLAGS:
                getattr(inv, _LIST_FLAGS[flag]).append(value)
            else:
                setattr(inv, _SCALAR_FLAGS[flag], value)
        elif tok.startswith("-") and tok != "-":
            raise TriggerError(f"unsupported flag in run: {tok}")
        else:
            prompt_parts.append(tok)
        i += 1
    inv.prompt = " ".join(prompt_parts) or None
    if operator == "play" and inv.prompt is None:
        inv.do_pass = True
    return inv


def normalize_trigger_run(run: str) -> str:
    """*run* as it should be stored: validated, and explicit about ``--pass``.

    A prompt-less ``play`` run gets ``--pass`` written out, so every surface
    that replays the string (the UI command bar included) gets a GM pass
    without having to know the default.
    """
    inv = parse_trigger_run(run)
    text = run.strip()
    if inv.operator == "play" and inv.prompt is None:
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        if "--pass" not in tokens:
            text = f"{text} --pass"
    return text


def run_operator_name(run: str) -> str:
    """The operator a ``run`` names (its first token), without full validation."""
    try:
        tokens = shlex.split(run or "")
    except ValueError:
        tokens = (run or "").split()
    if tokens and tokens[0] == "lens":
        tokens = tokens[1:]
    return tokens[0] if tokens else ""


# ---------------------------------------------------------------------------
# Session close: suggestions that still hold
# ---------------------------------------------------------------------------


@dataclass
class SessionEndOffers:
    markers: str = ""
    offered: list[str] = field(default_factory=list[str])
    rejected: list[str] = field(default_factory=list[str])


def check_suggestion(
    slug: str,
    *,
    declared: Mapping[str, Trigger],
    fired: set[str],
    parent: NarrativeNode | None,
) -> str | None:
    """Why *slug* cannot be offered at *parent*, or ``None`` when it can."""
    trig = declared.get(slug)
    if trig is None:
        return f"{slug}: no such trigger is declared"
    if slug in fired:
        return f"{slug}: already done ({trigger_node_name(slug)} exists)"
    if parent is not None and trig.declared_on not in ids_in_scope_at(parent):
        return (
            f"{slug}: declared on {trig.declared_on}, which is not in scope where "
            "the offer would be made (pinned there or above, or reached through a "
            "'+' pin), so play could never re-offer it if the player declines"
        )
    return None


def session_end_offers(
    child_text: str, kb: KnowledgeStore, parent: NarrativeNode
) -> SessionEndOffers:
    """Re-check a closing session's ``suggest`` ops against the world as written.

    Runs after materialization, so *kb* is expected to be a disk-truth store.
    Every suggestion that still holds becomes one marker line for the parent;
    the rest are reported, never silently dropped.
    """
    from lens.core.kb_pending import parse_kb_ops

    result = SessionEndOffers()
    slugs: list[str] = []
    for op in parse_kb_ops(child_text):
        if op.op == "suggest" and op.slug and op.slug not in slugs:
            slugs.append(op.slug)
    if not slugs:
        return result
    declared = declared_triggers(kb)
    fired = fired_slugs(parent.narrative_root)
    lines: list[str] = []
    for slug in slugs:
        reason = check_suggestion(slug, declared=declared, fired=fired, parent=parent)
        if reason is not None:
            result.rejected.append(reason)
            continue
        result.offered.append(slug)
        lines.append(render_suggest(slug))
    result.markers = "\n".join(lines)
    return result


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------


def find_trigger(kb: KnowledgeStore, slug: str) -> Trigger:
    """The declared trigger *slug*, or :class:`TriggerError`."""
    found = declared_triggers(kb).get(slug.strip().lower())
    if found is None:
        raise TriggerError(f"no trigger '{slug}' is declared")
    return found


async def fire_trigger(
    *,
    session: Any,
    narrative: NarrativeNode,
    slug: str,
    run: str | None = None,
    **callbacks: Any,
) -> Any:
    """Fire trigger *slug*: parse its ``run`` (or *run*, an edited copy) and open it.

    The one place a stored ``run`` turns into an operator call, shared by the
    CLI's accept prompt and ``lens trigger``.  The operator named by the run must
    match the slug's prefix; ``SessionOperator.run_session(trigger=…)`` does the
    rest (naming the node ``<slug>-tr``, refusing a done trigger).  *callbacks*
    pass through (``on_token``, ``cancel_event``, ``on_status``, …).
    """
    from lens.core.operators import get_operator_class_for_name
    from lens.core.operators.session import SessionOperator

    if slug.strip().lower() == ADVANCE_OFFER_SLUG:
        return await _fire_advance(
            session=session, narrative=narrative, run=run or "advance", **callbacks
        )
    trig = find_trigger(session.kb, slug)
    inv = parse_trigger_run(run if run is not None else trig.run)
    if not trig.slug.startswith(f"{inv.operator}-"):
        raise TriggerError(
            f"run starts with '{inv.operator}' but trigger {trig.slug} runs "
            f"'{trig.operator}'"
        )
    op_cls = get_operator_class_for_name(inv.operator)
    if op_cls is None or not issubclass(op_cls, SessionOperator):
        raise TriggerError(f"'{inv.operator}' is not a session operator")
    pins = list(inv.pins)
    extra: dict[str, Any] = {}
    if inv.operator == "play":
        # Same one-hop expansion `lens play --pin encounter.x` applies.
        pins = [
            p + "+" if p.startswith("encounter.") and not p.endswith("+") else p
            for p in pins
        ]
        if inv.do_pass:
            extra["pass"] = True
    if extra:
        callbacks["extra_params"] = extra
    return await op_cls.run_session(
        session=session,
        narrative=narrative,
        prompt=inv.prompt,
        module_ids=inv.module_ids,
        pins=pins,
        unpins=list(inv.unpins),
        mentions=list(inv.mentions),
        includes=list(inv.includes),
        llm_id=inv.llm_id,
        reasoning=inv.reasoning,
        trigger=trig.slug,
        **callbacks,
    )


_ADVANCE_RUN_FLAGS: Mapping[str, str] = {
    "--days": "days",
    "-d": "days",
    "--pin": "pins",
    "--unpin": "unpins",
    "--llm": "llm_id",
    "-l": "llm_id",
    "--reasoning": "reasoning",
}


def parse_advance_run(run: str) -> dict[str, Any]:
    """Parse the ``advance`` offer's run (as edited): ``advance [--days N] …``.

    The subset of ``lens advance`` that starts one: ``--days/-d``, ``--pin``,
    ``--unpin``, ``--llm/-l``, ``--reasoning``.  ``--end``/``--retry`` and a
    feedback argument are refused, because accepting the offer always starts a
    fresh advance.
    """
    try:
        tokens = shlex.split(run or "")
    except ValueError as e:
        raise TriggerError(f"cannot parse run: {e}") from e
    if tokens and tokens[0] == "lens":
        tokens = tokens[1:]
    if not tokens or tokens[0] != "advance":
        raise TriggerError("the advance offer must run 'advance'")
    out: dict[str, Any] = {"days": 1, "pins": [], "unpins": [], "llm_id": None, "reasoning": None}
    i = 1
    while i < len(tokens):
        flag, eq, inline = tokens[i].partition("=")
        key = _ADVANCE_RUN_FLAGS.get(flag)
        if key is None:
            raise TriggerError(f"unsupported in the advance offer: {tokens[i]}")
        if eq:
            value = inline
        else:
            i += 1
            if i >= len(tokens):
                raise TriggerError(f"{flag} needs a value")
            value = tokens[i]
        if key == "days":
            try:
                out["days"] = int(value)
            except ValueError as e:
                raise TriggerError(f"--days needs a number, got '{value}'") from e
        elif key in ("pins", "unpins"):
            out[key].append(value)
        else:
            out[key] = value
        i += 1
    return out


async def _fire_advance(
    *, session: Any, narrative: NarrativeNode, run: str, **callbacks: Any
) -> Any:
    """Accept the ``advance`` offer: start ``advance`` as ``lens advance`` would."""
    from lens.core.operators import get_operator_class_for_name

    parsed = parse_advance_run(run)
    op_cls = get_operator_class_for_name("advance")
    if op_cls is None:
        raise TriggerError("'advance' is not available (is the rpg dataset listed?)")
    passthrough = {
        k: v
        for k, v in callbacks.items()
        if k in ("on_token", "on_stream_target", "cancel_event")
    }
    return await getattr(op_cls, "run_advance")(
        session=session,
        narrative=narrative,
        increment=parsed["days"],
        pins=parsed["pins"],
        unpins=parsed["unpins"],
        llm_id=parsed["llm_id"],
        reasoning=parsed["reasoning"],
        **passthrough,
    )


# ---------------------------------------------------------------------------
# Validation — for hand-written triggers
# ---------------------------------------------------------------------------


def trigger_problems(kb: KnowledgeStore) -> list[str]:
    """Every trigger declaration that would be skipped, refused or never fire.

    :func:`triggers_from_text` is tolerant on purpose, so a play turn never
    breaks on one bad entry, which means a hand-written mistake disappears
    silently. This is the loud half: the
    same checks ``kb_set_trigger`` applies at write time, run over what is on
    disk, for ``lens check`` and ``lens trigger --all`` to report.
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    layer = kb.pending_layer()
    index = kb.resolved_index()
    for cid in sorted(index):
        if cid in layer.objects:
            text = layer.objects[cid]
        else:
            try:
                text = index[cid].path.read_text(encoding="utf-8")
            except OSError:
                continue
        if TRIGGERS_KEY not in text:
            continue
        raw = parse_front_matter(text).get(TRIGGERS_KEY)
        if raw is None:
            if _misplaced_triggers_block(text):
                problems.append(
                    f"{cid}: a 'triggers:' block is not the first thing in the file. "
                    "Front matter is only read from the very top: move the "
                    "[ … ]: # block above the body (and above any other comment)"
                )
            continue
        if not isinstance(raw, dict):
            problems.append(f"{cid}: 'triggers' must be a map of slug -> {{when, run}}")
            continue
        for slug_raw, entry in cast(dict[Any, Any], raw).items():
            slug = str(slug_raw)
            where = f"{cid} trigger '{slug}'"
            if not isinstance(entry, dict):
                problems.append(f"{where}: must be a map with 'when' and 'run'")
                continue
            data = cast(dict[str, Any], entry)
            when, run = data.get("when"), data.get("run")
            if not isinstance(when, str) or not when.strip():
                problems.append(f"{where}: 'when' is missing or empty")
            if not isinstance(run, str) or not run.strip():
                problems.append(f"{where}: 'run' is missing or empty")
                continue
            try:
                inv = parse_trigger_run(run)
            except TriggerError as e:
                problems.append(f"{where}: bad run — {e}")
                continue
            try:
                canonical = normalize_trigger_slug(slug, inv.operator)
            except TriggerError as e:
                problems.append(f"{where}: {e}")
                continue
            if canonical != slug:
                problems.append(
                    f"{where}: write it as '{canonical}' — a slug starts with "
                    "the operator its run uses"
                )
            other = seen.get(canonical)
            if other is not None:
                problems.append(
                    f"{where}: slug is also declared on {other}; only one of them is used"
                )
            seen.setdefault(canonical, cid)
    return problems


_TRIGGERS_LINE = re.compile(r"^\s+triggers:\s*$")


def _misplaced_triggers_block(text: str) -> bool:
    """A ``[ … ]: #`` comment holding ``triggers:`` that is not the front matter."""
    from lens.core.annotations import find_front_matter_span, iter_kept_storage_lines

    lines = text.split("\n")
    kept = {n for _, n in iter_kept_storage_lines(text)}
    span = find_front_matter_span(text)
    front: set[int] = set(range(span[0] + 1, span[1] + 1)) if span is not None else set()
    for number, line in enumerate(lines, start=1):
        if number in kept or number in front:
            continue
        if _TRIGGERS_LINE.match(line):
            return True
    return False
