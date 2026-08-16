"""Context-aware crawl and prompt assembly for operators.

The crawl pipeline is driven by a frozen :class:`CrawlSpec` capturing all
inputs (target node, extra pins, slice anchor, optional storage,
participants, current-passage override). :func:`crawl` returns a
:class:`CrawlResult` whose canonical content lives in a
:class:`~lens.core.crawl_graph.CrawlGraph`; legacy text fields
(``knowledge`` / ``previous_summaries`` / ``current_content`` /
``pinned_ids`` / ``remember_pins``) are read-only views over the graph.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from lens.core.annotations import parse_annotations
from lens.core.crawl_graph import (
    ComponentSource,
    CrawlComponent,
    CrawlGraph,
    CrawlTransform,
    RenderEffect,
    kb_ids_from_effects,
)
from lens.core.crawl_transforms import (
    AtExpansionTransform,
    ModuleTransform,
    ParticipantTransform,
    SecretDecodeTransform,
    StripStandaloneMountEmbedsTransform,
    expansion_policy_from_tags,
    is_state_tags,
)
from lens.core.knowledge import KnowledgeObject, KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.pinning import KB_PIN, KB_UNPIN
from lens.core.project import find_git_root_from
from lens.core.prompts import PromptStore
from lens.core.storage import Storage

logger = logging.getLogger(__name__)

REMEMBER_TAG_PREFIX = "remember."


def session_module_ids(
    node: NarrativeNode, *, operator_name: str, module_prefix: str
) -> tuple[str, ...]:
    """Read active modules for a session sub-node from its parent annotation.

    Returns the canonical KB ids — i.e. ``module_prefix + key`` — for each
    ``module`` entry on the parent's open ``[<operator_name>:<session_id>]``
    annotation.  Empty when *node* is not a session sub-node, when the operator
    does not match, or when the annotation has no ``module`` param.

    The param carries either one key (``module: encounter``) or several
    (``module: [encounter, clock]``); a session may run more than one module at
    a time, and each resolves independently — module text, its ``+`` links, and
    its ``<key>._template`` companion.  Order is the order the user gave, and
    duplicates collapse so ``--module encounter --module encounter`` is not two
    copies of the same prompt.
    """
    if not module_prefix or not node.key_path:
        return ()
    session_id = node.key_path[-1]
    parent = NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path[:-1],
    )
    if not parent.exists():
        return ()
    try:
        text = parent.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    for ann in reversed(parse_annotations(text)):
        if (
            ann.operator == operator_name
            and ann.id == session_id
            and not ann.closing
            and not ann.self_closing
        ):
            return _module_ids_from_param(ann.params.get("module"), module_prefix)
    return ()


def _module_ids_from_param(raw: Any, module_prefix: str) -> tuple[str, ...]:
    """Canonical module ids for a ``module`` annotation param.

    Accepts the scalar form (one key) and the sequence form (several), which is
    what YAML round-trips a one-or-many param as.
    """
    keys: list[Any] = []
    if isinstance(raw, str):
        keys = [raw]
    elif isinstance(raw, (list, tuple)):
        keys = list(cast(Sequence[Any], raw))
    out: list[str] = []
    for key in keys:
        if not isinstance(key, str) or not key.strip():
            continue
        kb_id = module_prefix + key.strip()
        if kb_id not in out:
            out.append(kb_id)
    return tuple(out)


def chat_session_extra_pins(node: NarrativeNode) -> list[str]:
    """KB ids from the parent ``[chat:…]`` open annotation (``as_kb_id`` / ``with_kb_id``)."""
    if not node.key_path:
        return []
    session_id = node.key_path[-1]
    parent = NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path[:-1],
    )
    if not parent.exists():
        return []
    try:
        text = parent.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    for ann in reversed(parse_annotations(text)):
        if (
            ann.operator == "chat"
            and ann.id == session_id
            and not ann.closing
            and not ann.self_closing
        ):
            out: list[str] = []
            p = ann.params
            for key in ("as_kb_id", "with_kb_id"):
                v = p.get(key)
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
            return out
    return []


def _expand_chat_participant_pins(ids: list[str], project_root: Path) -> list[str]:
    """Append ``+`` to ids that are valid KB ids without an existing ``+`` / ``++`` suffix."""
    if not ids:
        return ids
    kb_store = KnowledgeStore.for_project(project_root)
    out: list[str] = []
    for raw in ids:
        if not raw or raw.endswith("+"):
            out.append(raw)
            continue
        out.append(f"{raw}+" if kb_store.exists(raw) else raw)
    return out


def _remember_pins_subset(project_root: Path, pinned_ids: list[str]) -> dict[str, list[str]]:
    if not pinned_ids:
        return {}
    kb_store = KnowledgeStore.for_project(project_root)
    remember_pins: dict[str, list[str]] = {}
    prefix = REMEMBER_TAG_PREFIX
    for pid in pinned_ids:
        tags = [t for t in kb_store.get_tags(pid) if t.startswith(prefix)]
        if tags:
            remember_pins[pid] = tags
    return remember_pins


@dataclass
class SliceAnchor:
    """A fixed point in the narrative tree from which to start collecting text."""
    node: NarrativeNode
    line_end: int


def _empty_str_tuple() -> tuple[str, ...]:
    return ()


def _empty_participants() -> tuple[tuple[str, str], ...]:
    return ()


def _empty_params() -> dict[str, Any]:
    return {}


def _empty_mention_tuple() -> tuple[tuple[str, str], ...]:
    return ()


@dataclass(frozen=True)
class CrawlSpec:
    """Frozen description of what to crawl.

    The single argument to :func:`crawl`. Captures the target node and all
    knobs that previously rode in via keyword arguments (``extra_pins``,
    ``extra_unpins``, ``include_kb``, ``include_narrative``, ``anchor``,
    ``storage``, ``merge_chat_session_pins``) plus newer slots that used
    to ride sidecar channels (``current_passage_override`` for edit/collate;
    ``participants`` for chat; ``modules`` for session module KB ids).

    Set ``operator`` (plus ``operator_params``, ``session``, ``narrative``) on
    operator LLM crawls so :func:`crawl` merges active modality pins/unpins
    automatically. Prefer :meth:`~lens.core.operator.Operator.crawl_spec` when
    building specs from operator code.
    """

    node: NarrativeNode
    extra_pins: tuple[str, ...] = field(default_factory=_empty_str_tuple)
    extra_unpins: tuple[str, ...] = field(default_factory=_empty_str_tuple)
    include_kb: bool = True
    include_narrative: bool = True
    anchor: SliceAnchor | None = None
    storage: Storage | None = None
    merge_chat_session_pins: bool = True
    current_passage_override: str | None = None
    participants: tuple[tuple[str, str], ...] = field(default_factory=_empty_participants)
    modules: tuple[str, ...] = field(default_factory=_empty_str_tuple)
    operator: type[Any] | None = None
    operator_params: dict[str, Any] = field(default_factory=_empty_params)
    session: Any | None = None
    narrative: NarrativeNode | None = None
    pending_mentions: tuple[tuple[str, str], ...] = field(
        default_factory=_empty_mention_tuple
    )
    """``(kind, kb_id)`` mentions written by *this* invocation but not yet on disk.

    A fresh inline generation persists its annotation only after the model
    answers, so for exactly one turn the mention exists nowhere but here.  They
    render at the end of the cursor passage — byte-identical to where the
    persisted annotation lands, so the next beat reads it off disk unchanged.
    """

    @classmethod
    def of(cls, node: NarrativeNode, **kwargs: Any) -> CrawlSpec:
        """Build a CrawlSpec from a node + keyword arguments.

        Lists are normalised to tuples (the spec is frozen).
        """
        if "extra_pins" in kwargs and kwargs["extra_pins"] is not None:
            kwargs["extra_pins"] = tuple(kwargs["extra_pins"])
        else:
            kwargs.pop("extra_pins", None)
        if "extra_unpins" in kwargs and kwargs["extra_unpins"] is not None:
            kwargs["extra_unpins"] = tuple(kwargs["extra_unpins"])
        else:
            kwargs.pop("extra_unpins", None)
        participants_raw = kwargs.get("participants")
        if participants_raw is None:
            kwargs.pop("participants", None)
        elif isinstance(participants_raw, dict):
            participants_dict = cast(dict[str, str], participants_raw)
            kwargs["participants"] = tuple(participants_dict.items())
        else:
            participants_seq = cast(Sequence[tuple[str, str]], participants_raw)
            kwargs["participants"] = tuple(participants_seq)
        if "modules" in kwargs and kwargs["modules"] is not None:
            kwargs["modules"] = tuple(kwargs["modules"])
        else:
            kwargs.pop("modules", None)
        if "operator_params" in kwargs and kwargs["operator_params"] is not None:
            kwargs["operator_params"] = dict(kwargs["operator_params"])
        else:
            kwargs.pop("operator_params", None)
        return cls(node=node, **kwargs)

    def with_operator(
        self,
        operator: type[Any],
        params: Mapping[str, Any] | None = None,
        *,
        session: Any | None = None,
        narrative: NarrativeNode | None = None,
    ) -> CrawlSpec:
        """Return a copy that runs modality resolution when passed to :func:`crawl`."""
        return replace(
            self,
            operator=operator,
            operator_params=dict(params or {}),
            session=session,
            narrative=narrative,
        )


class CrawlResult:
    """Result of a crawl: a graph plus its render effects.

    The text-shaped views (``knowledge``, ``previous_summaries``,
    ``current_content``, ``pinned_ids``, ``remember_pins``) are read-only
    derivations from ``graph``.  Mutate the graph directly to change them.
    """

    __slots__ = (
        "graph",
        "project_root",
        "current_node",
        "render_effects",
        "render_graph",
        "modality_resolution",
        "modality_context",
        "pending_mentions",
    )

    def __init__(
        self,
        graph: CrawlGraph,
        *,
        project_root: Path | None = None,
        current_node: NarrativeNode | None = None,
        render_effects: tuple[RenderEffect, ...] = (),
        pending_mentions: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.graph: CrawlGraph = graph
        self.project_root = project_root
        self.current_node = current_node
        self.render_effects = render_effects
        # Carried from the spec so the turns path in ``Operator.build_messages``
        # renders the cursor node exactly as ``crawl`` rendered it here.
        self.pending_mentions = pending_mentions
        # Set by assemble_prompt(): the post-transform graph that produced the
        # messages, kept so read-only consumers (``lens explain``) can report
        # exactly what was rendered without re-assembling it themselves.
        self.render_graph: CrawlGraph | None = None
        self.modality_resolution: Any | None = None
        self.modality_context: Any | None = None

    @classmethod
    def from_text_fields(
        cls,
        *,
        knowledge: list[str] | None = None,
        previous_summaries: list[str] | None = None,
        current_content: str | None = None,
        pinned_ids: list[str] | None = None,
        remember_pins: dict[str, list[str]] | None = None,
        project_root: Path | None = None,
        current_node: NarrativeNode | None = None,
    ) -> CrawlResult:
        """Build a CrawlResult from raw text fields (test/synthesis helper).

        Use this when constructing a result by hand for a test or for code
        that doesn't have a graph yet.  Production code paths should build a
        :class:`CrawlGraph` directly and call the regular constructor.
        """
        graph = _graph_from_text_fields(
            project_root=project_root,
            knowledge=knowledge or [],
            previous_summaries=previous_summaries or [],
            current_content=current_content,
            pinned_ids=pinned_ids or [],
            remember_pins=remember_pins or {},
        )
        return cls(graph=graph, project_root=project_root, current_node=current_node)

    @property
    def knowledge(self) -> list[str]:
        return [
            component.text
            for component in self.graph.components
            if component.kind in {"knowledge", "reference"}
            and "llm" in component.visibility
        ]

    @property
    def previous_summaries(self) -> list[str]:
        return [
            component.text
            for component in self.graph.components
            if component.kind == "narrative_summary" and "llm" in component.visibility
        ]

    @property
    def current_content(self) -> str | None:
        for component in self.graph.components:
            if (
                component.kind == "current_narrative"
                and "llm" in component.visibility
            ):
                return component.text
        return None

    @property
    def pinned_ids(self) -> list[str]:
        return list(self.graph.pinned_ids)

    @property
    def remember_pins(self) -> dict[str, list[str]]:
        return {
            key: list(value) for key, value in self.graph.remember_pins.items()
        }

    def scoped_kb_ids(self) -> set[str]:
        """Every KB id the model can already see, lowercased.

        ``pinned_ids`` is the effective post-walk pin set — front matter,
        operator params, modality auto-pins, ``+`` link expansion, and session
        modules (:class:`~lens.core.crawl_transforms.ModuleTransform` appends to
        it).  Mentions and includes are not pins: they expand in place and leave
        a ``kb-mention`` / ``kb-include`` render effect instead, so they are
        added here from the effects.

        Used to answer "is this object already in scope by *any* route", which
        is what decides whether a module is still worth offering to the model
        (see :mod:`lens.core.module_requests`) and which ``rules.<type>``
        companions play should bring along.
        """
        scoped = {kid.rstrip("+").lower() for kid in self.graph.pinned_ids}
        scoped.update(
            kid.rstrip("+").lower()
            for kid in kb_ids_from_effects(
                (*self.graph.effects, *self.render_effects)
            )
        )
        return scoped

    @property
    def state_pins(self) -> list[str]:
        """Pinned ids tagged `state`, in pin order.

        Read off the same component metadata the render-time divert uses
        (:func:`_divert_state_components`), so surfaces that show pins cannot
        disagree with the prompt about which objects render at the tail.
        """
        ids: list[str] = []
        for component in self.graph.components:
            kb_id = component.metadata.get("kb_id")
            if not kb_id or kb_id in ids:
                continue
            tags = component.metadata.get("tags", "")
            if is_state_tags(tag for tag in tags.split(",") if tag):
                ids.append(kb_id)
        return ids


def wrap_block(title: str, body: str) -> str:
    """Wrap *body* in the ``--- begin/end <title> ---`` framing used in prompts.

    Returns an empty string for empty bodies (the block is then omitted).
    """
    body_stripped = body.strip()
    if not body_stripped:
        return ""
    return f"--- begin {title} ---\n{body_stripped}\n--- end {title} ---"


BLOCK_SYSTEM = "system"
BLOCK_KNOWLEDGE = "relevant_knowledge"
BLOCK_PREVIOUS = "previous_events_summary"
BLOCK_CURRENT = "current_passage"
BLOCK_EXTRA = "extra"
BLOCK_STATE = "live_state"
BLOCK_TASK = "task"

_KIND_TO_BLOCK: dict[str, str] = {
    "system": BLOCK_SYSTEM,
    "knowledge": BLOCK_KNOWLEDGE,
    "reference": BLOCK_KNOWLEDGE,
    "state": BLOCK_STATE,
    "narrative_summary": BLOCK_PREVIOUS,
    "current_narrative": BLOCK_CURRENT,
    "extra": BLOCK_EXTRA,
    "task": BLOCK_TASK,
}


def prompt_block_for_component(component: CrawlComponent) -> str | None:
    """Return the prompt block a rendered *component* lands in, or ``None``.

    ``None`` means the component contributes no bytes to the model messages —
    either its kind is never rendered (``participant``, ``warning``, …) or it
    is not LLM-visible.  Mirrors the selection rules in
    :func:`_sections_from_graph`.
    """
    if "llm" not in component.visibility:
        return None
    return _KIND_TO_BLOCK.get(component.kind)


def ancestor_chain(node: NarrativeNode) -> list[NarrativeNode]:
    chain: list[NarrativeNode] = []
    for depth in range(len(node.key_path) + 1):
        chain.append(
            NarrativeNode(
                narrative_root=node.narrative_root,
                key_path=node.key_path[:depth],
            )
        )
    return chain


def _pin_origin_fields(
    level: int, raw: str, ancestors: list[NarrativeNode]
) -> dict[str, str]:
    """Describe where a surviving pin came from (ancestor level or extras)."""
    if level < len(ancestors):
        return {
            "pin_source": "node",
            "pin_level": str(level),
            "pin_node": ancestors[level].path_str(),
            "pin_raw": raw,
        }
    return {"pin_source": "extra", "pin_level": str(level), "pin_raw": raw}


def _resolve_pins_for_ancestors(
    project_root: Path,
    ancestors: list[NarrativeNode],
    storage: Storage,
    *,
    extra_pins: list[str] | None = None,
    extra_unpins: list[str] | None = None,
    include_kb: bool,
) -> tuple[list[str], list[str], list[CrawlComponent]]:
    """Resolve pins/unpins across *ancestors* and optional extras."""
    kb_store = KnowledgeStore.for_project(project_root)

    all_pins: list[tuple[int, str]] = []
    unpin_levels: dict[str, set[int]] = {}

    for level, anc in enumerate(ancestors):
        if not anc.exists():
            continue
        fm = anc.front_matter()
        raw_pins = fm.get(KB_PIN)
        pins: list[str] = []
        if isinstance(raw_pins, list):
            for item in raw_pins:  # pyright: ignore[reportUnknownVariableType]
                if isinstance(item, str):
                    pins.append(item)
        for kid in pins:
            all_pins.append((level, kid))
        raw_unpins = fm.get(KB_UNPIN)
        unpins_list: list[str] = []
        if isinstance(raw_unpins, list):
            for item in raw_unpins:  # pyright: ignore[reportUnknownVariableType]
                if isinstance(item, str):
                    unpins_list.append(item)
        for kid in unpins_list:
            unpin_levels.setdefault(kid.rstrip("+"), set()).add(level)

    max_level = len(ancestors) - 1
    extra_level = max_level + 1
    for kid in extra_pins or []:
        all_pins.append((extra_level, kid))
    for kid in extra_unpins or []:
        base = kid.rstrip("+")
        unpin_levels.setdefault(base, set()).add(extra_level)

    def pin_survives(level: int, raw_id: str) -> bool:
        base = raw_id.rstrip("+")
        unpins = unpin_levels.get(base, set())
        return not any(u >= level for u in unpins)

    surviving: list[tuple[int, str]] = [
        (lev, raw) for lev, raw in all_pins if pin_survives(lev, raw)
    ]
    surviving.sort(key=lambda x: x[0])
    seen_base: set[str] = set()
    ordered_base: list[tuple[int, str]] = []
    for lev, raw in surviving:
        base = raw.rstrip("+")
        if base not in seen_base:
            seen_base.add(base)
            ordered_base.append((lev, raw))

    all_unpinned: set[str] = set(unpin_levels.keys())

    if not include_kb:
        return [], [], []

    knowledge_formatted: list[str] = []
    pinned_ids: list[str] = []
    knowledge_components: list[CrawlComponent] = []

    effective_ids: list[str] = []
    all_objects: dict[str, KnowledgeObject] = {}
    # Per effective id: how it got here (which ancestor level pinned it, and
    # whether it arrived directly or through a `+` expansion).  Carried into
    # component metadata so `lens explain` can answer "why is this here".
    pin_origin: dict[str, dict[str, str]] = {}
    for level, raw in ordered_base:
        base = raw.rstrip("+")
        origin = _pin_origin_fields(level, raw, ancestors)
        if not raw.endswith("+"):
            effective_ids.append(base)
            pin_origin.setdefault(base, origin)
            objs = kb_store.get_objects([base])
            all_objects.update(objs)
        else:
            ordered_ids, objects = kb_store.get_objects_with_links([raw])
            for cid in ordered_ids:
                if cid not in all_unpinned and cid not in effective_ids:
                    effective_ids.append(cid)
                    if cid == base:
                        pin_origin.setdefault(cid, origin)
                    else:
                        pin_origin.setdefault(
                            cid, {**origin, "pin_expanded_from": base}
                        )
            all_objects.update(objects)

    for cid in effective_ids:
        obj = all_objects.get(cid)
        if obj is not None:
            normalized = storage.normalize_raw_text(obj.text, source_id=f"kb:{cid}")
            knowledge_formatted.append(
                storage.format_kb_prompt_block(
                    canonical_id=cid,
                    text=normalized.raw_storage_text,
                    tags=obj.tags,
                    include_comments=False,
                    source_id=f"kb:{cid}",
                )
            )
            knowledge_components.append(
                CrawlComponent(
                    id=f"kb:{cid}",
                    kind="knowledge",
                    text=knowledge_formatted[-1],
                    source=ComponentSource(
                        kind="knowledge",
                        identifier=cid,
                        metadata=dict(pin_origin.get(cid, {})),
                    ),
                    priority=len(knowledge_components),
                    metadata={
                        "kb_id": cid,
                        "tags": ",".join(obj.tags),
                        "expansion_policy": expansion_policy_from_tags(obj.tags).mode,
                        **pin_origin.get(cid, {}),
                    },
                )
            )
            pinned_ids.append(cid)

    return knowledge_formatted, pinned_ids, knowledge_components


def spine_path(
    anchor_node: NarrativeNode, cursor_node: NarrativeNode
) -> list[NarrativeNode]:
    """Return the ordered list of nodes on the shortest path between two nodes."""
    a_path = anchor_node.key_path
    c_path = cursor_node.key_path

    lca_depth = 0
    for i in range(min(len(a_path), len(c_path))):
        if a_path[i] == c_path[i]:
            lca_depth = i + 1
        else:
            break

    path: list[NarrativeNode] = []
    for depth in range(len(a_path), lca_depth - 1, -1):
        path.append(
            NarrativeNode(
                narrative_root=anchor_node.narrative_root,
                key_path=a_path[:depth],
            )
        )

    for depth in range(lca_depth + 1, len(c_path) + 1):
        path.append(
            NarrativeNode(
                narrative_root=cursor_node.narrative_root,
                key_path=c_path[:depth],
            )
        )

    return path


CursorMentionRenderer = Callable[[str], "tuple[str, list[str], list[Any]]"]
"""Renders the cursor node's raw text with live mentions expanded in place.

Returns ``(expanded_text, state_tagged_ids, expansions)`` — see
:func:`~lens.core.mentions.render_mentions_in_place`.
"""


def cursor_mention_renderer(
    *,
    project_root: Path,
    storage: Storage,
    pinned_ids: Sequence[str],
    pending_mentions: Sequence[tuple[str, str]] = (),
) -> CursorMentionRenderer:
    """Build the renderer used by :func:`crawl` and ``Operator.build_messages``.

    Both must expand identically — one builds the ``[CURRENT PASSAGE]``
    component, the other re-parses the same node into conversation turns — so
    they share this factory rather than each assembling the arguments.
    """
    from lens.core.mentions import MentionRef, render_mentions_in_place

    pending = tuple(
        MentionRef(kind=cast(Any, kind), kb_id=kb_id, line=_PENDING_MENTION_LINE)
        for kind, kb_id in pending_mentions
    )

    def render(raw: str) -> tuple[str, list[str], list[Any]]:
        return render_mentions_in_place(
            raw,
            project_root=project_root,
            storage=storage,
            pinned_ids=pinned_ids,
            pending=pending,
        )

    return render


_PENDING_MENTION_LINE = 1 << 30
"""Any line past the end of the buffer; ``render_mentions_in_place`` clamps it
to end-of-text, which is where the annotation will be persisted."""


def _add_mention_state_components(
    graph: CrawlGraph,
    state_ids: Sequence[str],
    *,
    project_root: Path,
    storage: Storage,
) -> None:
    """Add `state`-tagged mentions as components so they render at the tail.

    A mentioned object tagged ``state`` is deliberately *not* inlined into the
    passage: its content changes between beats, and inlining would freeze a
    snapshot into the append-only transcript — the exact cost tagging it
    ``state`` asks Lens to avoid.  Added here as an ordinary knowledge
    component, it is picked up by :func:`_divert_state_components` at render
    time and lands in ``[LIVE STATE]`` before ``[TASK]`` like any other.
    """
    if not state_ids:
        return
    kb_store = KnowledgeStore.for_project(project_root)
    objects = kb_store.get_objects(list(state_ids))
    for kb_id in state_ids:
        obj = objects.get(kb_id) or objects.get(kb_id.lower())
        component_id = f"mention-kb:{kb_id}"
        if obj is None or graph.component_by_id(component_id) is not None:
            continue
        graph.add_component(
            CrawlComponent(
                id=component_id,
                kind="knowledge",
                text=storage.format_kb_prompt_block(
                    canonical_id=obj.id,
                    text=obj.text,
                    tags=obj.tags,
                    include_comments=False,
                    source_id=f"mention:{obj.id}",
                ),
                source=ComponentSource(kind="knowledge", identifier=obj.id),
                priority=len(graph.components),
                metadata={
                    "kb_id": obj.id,
                    "tags": ",".join(obj.tags),
                    "expansion_policy": "reference",
                    "mention_scope": "state",
                },
            )
        )
        if obj.id not in graph.pinned_ids:
            graph.pinned_ids.append(obj.id)


def _collect_spine_narrative(
    anchor: SliceAnchor,
    cursor_node: NarrativeNode,
    *,
    storage: Storage,
    expand_cursor: CursorMentionRenderer | None = None,
) -> tuple[list[str], str | None, list[str], list[Any]]:
    """Collect narrative text along the spine from *anchor* to *cursor_node*.

    Returns ``(previous_summaries, current_content, state_mention_ids, expansions)``.
    *expand_cursor* renders mentions in place, and only ever runs on the cursor
    node: includes and mentions are node-local and never inherited, so ancestor
    prose on the spine is stripped exactly as before.
    """
    path = spine_path(anchor.node, cursor_node)

    previous_summaries: list[str] = []
    current_content: str | None = None
    state_mention_ids: list[str] = []
    expansions: list[Any] = []

    for node in path:
        if not node.exists():
            continue
        text = storage.normalize_path_text(node.md_path()).raw_storage_text

        if node.key_path == anchor.node.key_path:
            lines = text.split("\n")
            text = "\n".join(lines[anchor.line_end - 1 :])

        is_cursor = node.key_path == cursor_node.key_path
        if is_cursor and expand_cursor is not None:
            text, state_mention_ids, expansions = expand_cursor(text)

        stripped = storage.normalize_raw_text(text).strip_comments_text
        if not stripped.strip():
            continue

        if is_cursor:
            current_content = stripped
        else:
            previous_summaries.append(stripped)

    return previous_summaries, current_content, state_mention_ids, expansions


def _narrative_component(
    *,
    node: NarrativeNode,
    text: str,
    kind: str,
    priority: int,
) -> CrawlComponent:
    if kind == "current":
        component_kind = "current_narrative"
    else:
        component_kind = "narrative_summary"
    return CrawlComponent(
        id=f"narrative:{node.path_str()}:{component_kind}",
        kind=component_kind,
        text=text,
        source=ComponentSource(
            kind="narrative",
            identifier=node.path_str(),
            path=node.md_path(),
        ),
        priority=priority,
        metadata={"node": node.path_str()},
    )


def _override_current_component(
    *,
    text: str,
    project_root: Path | None,
    priority: int,
) -> CrawlComponent:
    return CrawlComponent(
        id="current-override",
        kind="current_narrative",
        text=text,
        source=ComponentSource(
            kind="operator",
            identifier="current_passage_override",
            path=project_root,
        ),
        priority=priority,
        metadata={"override": "true"},
    )


def _build_base_graph(
    *,
    project_root: Path,
    knowledge_components: list[CrawlComponent],
    previous_components: list[CrawlComponent],
    current_component: CrawlComponent | None,
    pinned_ids: list[str],
    remember_pins: dict[str, list[str]],
) -> CrawlGraph:
    graph = CrawlGraph(
        project_root=project_root,
        pinned_ids=list(pinned_ids),
        remember_pins={key: list(value) for key, value in remember_pins.items()},
    )
    graph.extend_components(knowledge_components)
    graph.extend_components(previous_components)
    if current_component is not None:
        graph.add_component(current_component)
        graph.current_node_component_id = current_component.id
    return graph


def _collect_vars(ancestors: list[NarrativeNode]) -> dict[str, str]:
    vars_map: dict[str, str] = {}
    for anc in ancestors:
        if not anc.exists():
            continue
        raw_vars = anc.front_matter().get("vars")
        if not isinstance(raw_vars, dict):
            continue
        for key, value in raw_vars.items():  # pyright: ignore[reportUnknownVariableType]
            if isinstance(key, str) and isinstance(value, str):
                vars_map[key] = value
    return vars_map


def collect_vars(node: NarrativeNode) -> dict[str, str]:
    """Return the inherited ``vars`` map for *node* (front-matter, root→leaf)."""
    return _collect_vars(ancestor_chain(node))


def apply_transforms_to_result(
    crawl_result: CrawlResult,
    transforms: Sequence[CrawlTransform],
) -> None:
    """Apply *transforms* to *crawl_result.graph* in place."""
    if not transforms:
        return
    graph = crawl_result.graph
    for t in transforms:
        graph = t.apply(graph)
    crawl_result.graph = graph
    crawl_result.render_effects = tuple(graph.effects)


def _apply_default_transforms(
    graph: CrawlGraph,
    *,
    project_root: Path,
    storage: Storage,
) -> CrawlGraph:
    graph = SecretDecodeTransform().apply(graph)
    graph = AtExpansionTransform(project_root=project_root, storage=storage).apply(graph)
    graph = StripStandaloneMountEmbedsTransform().apply(graph)
    return graph


def crawl(spec: CrawlSpec | NarrativeNode, **kwargs: Any) -> CrawlResult:
    """Crawl the narrative + KB context.

    Accepts either a :class:`CrawlSpec` (preferred) or a
    :class:`~lens.core.narrative.NarrativeNode` plus the legacy keyword
    arguments (``extra_pins``, ``extra_unpins``, ``include_kb``,
    ``include_narrative``, ``anchor``, ``storage``,
    ``merge_chat_session_pins``); the node form is normalised into a
    spec before execution.
    """
    if isinstance(spec, NarrativeNode):
        spec = CrawlSpec.of(spec, **kwargs)
    elif kwargs:
        raise TypeError(
            "crawl(): pass either a CrawlSpec or a NarrativeNode + kwargs, not both"
        )

    modality_resolution: Any | None = None
    modality_context: Any | None = None
    if spec.operator is not None:
        from lens.core.modalities.apply import apply_operator_modalities_for_crawl

        spec, modality_resolution, modality_context = apply_operator_modalities_for_crawl(
            spec
        )

    node = spec.node
    project_root = node.narrative_root.parent.parent
    local_storage = spec.storage or Storage(find_git_root_from(project_root))
    ancestors = ancestor_chain(node)

    extra_pins_list: list[str] = list(spec.extra_pins)
    if spec.merge_chat_session_pins:
        chat_extras = chat_session_extra_pins(node)
        if chat_extras:
            chat_extras = _expand_chat_participant_pins(chat_extras, project_root)
            extra_pins_list = [*chat_extras, *extra_pins_list]
    merged_extra: list[str] | None = extra_pins_list or None
    extra_unpins_arg: list[str] | None = list(spec.extra_unpins) or None

    _, pinned_ids, knowledge_components = _resolve_pins_for_ancestors(
        project_root,
        ancestors,
        local_storage,
        extra_pins=merged_extra,
        extra_unpins=extra_unpins_arg,
        include_kb=spec.include_kb,
    )
    remember_pins = (
        _remember_pins_subset(project_root, pinned_ids) if spec.include_kb else {}
    )

    # Includes and mentions expand in place, in the cursor node only, so this
    # renderer is built after pins resolve (already-pinned ids are suppressed)
    # and never runs on ancestor prose.
    expand_cursor: CursorMentionRenderer | None = None
    if spec.include_narrative:
        expand_cursor = cursor_mention_renderer(
            project_root=project_root,
            storage=local_storage,
            pinned_ids=pinned_ids,
            pending_mentions=spec.pending_mentions,
        )

    previous_components: list[CrawlComponent] = []
    current_component: CrawlComponent | None = None
    state_mention_ids: list[str] = []
    mention_expansions: list[Any] = []
    if spec.include_narrative:
        if spec.anchor is not None:
            previous_summaries, current_content, state_mention_ids, mention_expansions = (
                _collect_spine_narrative(
                    spec.anchor,
                    node,
                    storage=local_storage,
                    expand_cursor=expand_cursor,
                )
            )
            path = spine_path(spec.anchor.node, node)
            previous_index = 0
            for path_node in path:
                if not path_node.exists() or path_node.key_path == node.key_path:
                    continue
                if previous_index >= len(previous_summaries):
                    break
                previous_components.append(
                    _narrative_component(
                        node=path_node,
                        text=previous_summaries[previous_index],
                        kind="summary",
                        priority=previous_index,
                    )
                )
                previous_index += 1
            if current_content:
                current_component = _narrative_component(
                    node=node,
                    text=current_content,
                    kind="current",
                    priority=len(previous_components),
                )
        else:
            for anc in ancestors[:-1]:
                if not anc.exists():
                    continue
                stripped = local_storage.normalize_path_text(
                    anc.md_path()
                ).strip_comments_text
                if stripped.strip():
                    previous_components.append(
                        _narrative_component(
                            node=anc,
                            text=stripped,
                            kind="summary",
                            priority=len(previous_components),
                        )
                    )
            current_node_anc = ancestors[-1]
            if current_node_anc.exists():
                normalized = local_storage.normalize_path_text(
                    current_node_anc.md_path()
                )
                stripped = normalized.strip_comments_text
                if expand_cursor is not None:
                    expanded, state_mention_ids, mention_expansions = expand_cursor(
                        normalized.raw_storage_text
                    )
                    if expanded != normalized.raw_storage_text:
                        stripped = local_storage.normalize_raw_text(
                            expanded,
                            source_id=f"mentions:{current_node_anc.path_str()}",
                        ).strip_comments_text
                if stripped.strip():
                    current_component = _narrative_component(
                        node=current_node_anc,
                        text=stripped,
                        kind="current",
                        priority=len(previous_components),
                    )

    if spec.current_passage_override is not None:
        # The override *replaces* the passage, so anything derived from the
        # node's own text no longer describes what is being sent — deriving it
        # there would put a `state` mention into [LIVE STATE], and effects
        # claiming expansions, for text the prompt never contains.  Re-deriving
        # from the override keeps the two in step: `edit` / `collate` pass
        # comment-stripped text, where this finds nothing and is a no-op, while
        # `explain --line` passes a raw truncation and gets the same expansion
        # (and the same pin suppression) the un-truncated path would give it.
        override_text = spec.current_passage_override
        state_mention_ids, mention_expansions = [], []
        if override_text:
            if expand_cursor is not None:
                override_text, state_mention_ids, mention_expansions = expand_cursor(
                    override_text
                )
            override_text = local_storage.normalize_raw_text(
                override_text
            ).strip_comments_text
        current_component = (
            _override_current_component(
                text=override_text,
                project_root=project_root,
                priority=len(previous_components),
            )
            if override_text.strip()
            else None
        )

    current_node = ancestors[-1] if ancestors[-1].exists() else None
    graph = _build_base_graph(
        project_root=project_root,
        knowledge_components=knowledge_components,
        previous_components=previous_components,
        current_component=current_component,
        pinned_ids=pinned_ids,
        remember_pins=remember_pins,
    )
    graph.vars.update(_collect_vars(ancestors))
    _add_mention_state_components(
        graph, state_mention_ids, project_root=project_root, storage=local_storage
    )
    for expansion in mention_expansions:
        # The block is spliced into the passage rather than added as its own
        # component, so this effect is the only trace that it happened — and
        # `lens explain` needs it to answer "did my mention land".
        graph.add_effect(
            RenderEffect(
                kind=f"kb-{expansion.kind}",
                token=expansion.kb_id,
                result=str(expansion.bytes),
                source_component_id=graph.current_node_component_id or "",
                details={"text": expansion.text},
            )
        )

    if spec.participants:
        ParticipantTransform(participants=dict(spec.participants)).apply(graph)

    if spec.modules:
        ModuleTransform(
            module_ids=spec.modules,
            project_root=project_root,
            storage=local_storage,
        ).apply(graph)

    graph = _apply_default_transforms(
        graph, project_root=project_root, storage=local_storage
    )
    result = CrawlResult(
        graph,
        project_root=project_root,
        current_node=current_node,
        render_effects=tuple(graph.effects),
        pending_mentions=spec.pending_mentions,
    )
    if modality_resolution is not None and modality_context is not None:
        from lens.core.modalities.apply import attach_modality_resolution_to_crawl

        attach_modality_resolution_to_crawl(
            result,
            resolved=modality_resolution,
            ctx=modality_context,
        )
    return result


def _graph_from_text_fields(
    *,
    project_root: Path | None,
    knowledge: list[str],
    previous_summaries: list[str],
    current_content: str | None,
    pinned_ids: list[str],
    remember_pins: dict[str, list[str]],
) -> CrawlGraph:
    """Build a fresh graph from raw text fields (test/legacy construction)."""
    graph = CrawlGraph(
        project_root=project_root,
        pinned_ids=list(pinned_ids),
        remember_pins={key: list(value) for key, value in remember_pins.items()},
    )
    for index, text in enumerate(knowledge):
        graph.add_component(
            CrawlComponent(
                id=f"legacy-knowledge-{index + 1}",
                kind="knowledge",
                text=text,
                priority=index,
                source=ComponentSource(kind="system", identifier="legacy-crawl-result"),
            )
        )
    for index, text in enumerate(previous_summaries):
        graph.add_component(
            CrawlComponent(
                id=f"legacy-summary-{index + 1}",
                kind="narrative_summary",
                text=text,
                priority=index,
                source=ComponentSource(kind="system", identifier="legacy-crawl-result"),
            )
        )
    if current_content:
        graph.add_component(
            CrawlComponent(
                id="legacy-current",
                kind="current_narrative",
                text=current_content,
                priority=len(previous_summaries),
                source=ComponentSource(kind="system", identifier="legacy-crawl-result"),
            )
        )
        graph.current_node_component_id = "legacy-current"
    return graph


def _clone_graph(graph: CrawlGraph) -> CrawlGraph:
    """Deep-copy a graph for render-time mutation."""
    cloned = CrawlGraph(
        project_root=graph.project_root,
        metadata=dict(graph.metadata),
        vars=dict(graph.vars),
        pinned_ids=list(graph.pinned_ids),
        remember_pins={key: list(value) for key, value in graph.remember_pins.items()},
        current_node_component_id=graph.current_node_component_id,
    )
    cloned.extend_components(component.clone_with() for component in graph.components)
    for effect in graph.effects:
        cloned.add_effect(effect)
    return cloned


def _prepare_render_graph(
    result: CrawlResult,
    *,
    system_prompt: str,
    instruction: str,
    extra_sections: list[str] | None = None,
) -> CrawlGraph:
    graph = _clone_graph(result.graph)
    graph.add_component(
        CrawlComponent(
            id="render-system",
            kind="system",
            text=system_prompt,
            role="system",
            source=ComponentSource(kind="operator", identifier="system_prompt"),
            priority=-100,
        )
    )
    for index, section in enumerate(extra_sections or []):
        if section:
            graph.add_component(
                CrawlComponent(
                    id=f"render-extra-{index + 1}",
                    kind="extra",
                    text=section,
                    role="user",
                    source=ComponentSource(kind="operator", identifier="extra_section"),
                    priority=50 + index,
                )
            )
    graph.add_component(
        CrawlComponent(
            id="render-task",
            kind="task",
            text=instruction,
            role="user",
            source=ComponentSource(kind="operator", identifier="instruction"),
            priority=100,
        )
    )
    if graph.project_root is not None:
        try:
            storage = Storage(find_git_root_from(graph.project_root))
        except RuntimeError:
            logger.debug(
                "render graph: no git root for %s; skipping AtExpansionTransform",
                graph.project_root,
            )
            graph = SecretDecodeTransform().apply(graph)
            graph = StripStandaloneMountEmbedsTransform().apply(graph)
        else:
            graph = _apply_default_transforms(
                graph, project_root=graph.project_root, storage=storage
            )
    else:
        logger.debug("render graph: no project_root; skipping AtExpansionTransform")
        graph = SecretDecodeTransform().apply(graph)
        graph = StripStandaloneMountEmbedsTransform().apply(graph)
    _divert_state_components(graph)
    _log_render_effects_if_verbose(graph)
    return graph


def _divert_state_components(graph: CrawlGraph) -> None:
    """Reclassify `state`-tagged KB components so they render at the tail.

    Runs once, after every transform has contributed its components, so it
    covers all the ways a KB object can enter scope — ancestor front-matter
    pins, session modules, rules companions, `@` mentions — with one branch
    instead of one per construction site.  Running last is also what makes the
    divert land *after* id dedup: components that would collide were already
    skipped at build time, so an object that is both pinned and mentioned is a
    single component here and moves to the tail once.
    """
    for component in graph.components:
        if component.kind not in {"knowledge", "reference"}:
            continue
        tags = component.metadata.get("tags", "")
        if not is_state_tags(tag for tag in tags.split(",") if tag):
            continue
        component.kind = "state"
        component.transform_history.append("state-divert")
        graph.add_effect(
            RenderEffect(
                kind="kb-state",
                token=component.metadata.get("kb_id", component.id),
                result=BLOCK_STATE,
                source_component_id=component.id,
            )
        )


def _log_render_effects_if_verbose(graph: CrawlGraph) -> None:
    if not graph.project_root or not graph.effects:
        return
    lens_toml = graph.project_root / "lens.toml"
    if not lens_toml.exists():
        return
    import tomllib
    try:
        with lens_toml.open("rb") as _f:
            _cfg = tomllib.load(_f)
    except (OSError, tomllib.TOMLDecodeError):
        return
    verbose = bool(_cfg.get("project", {}).get("verbose_llm", False)) or bool(
        _cfg.get("dataset", {}).get("verbose_llm", False)
    )
    if not verbose:
        return
    sep = "─" * 40
    body = "\n".join(
        f"  {e.kind} {e.token!r} -> {e.result!r}" + ("  (sticky)" if e.sticky else "")
        for e in graph.effects
    )
    logger.info("\n%s\n[RENDER EFFECTS]\n%s\n%s", sep, body, sep)


def _block_from_components(title: str, components: list[CrawlComponent]) -> str:
    return wrap_block(title, "\n\n".join(component.text for component in components))


def _system_content_from_graph(graph: CrawlGraph, prompts: PromptStore) -> str:
    system = next(
        (component for component in graph.components if component.kind == "system"),
        None,
    )
    text = system.text if system is not None else ""
    return text


def _task_block_from_graph(graph: CrawlGraph, prompts: PromptStore) -> str:
    task = next((component for component in graph.components if component.kind == "task"), None)
    instruction = task.text if task is not None else ""
    return wrap_block(prompts.get("shared.block.task"), instruction) or instruction


def _sections_from_graph(graph: CrawlGraph, prompts: PromptStore) -> list[str]:
    sections: list[str] = []
    knowledge = [
        component
        for component in graph.components
        if component.kind in {"knowledge", "reference"} and "llm" in component.visibility
    ]
    if knowledge:
        kb_block = _block_from_components(prompts.get("shared.block.relevant_knowledge"), knowledge)
        if kb_block:
            sections.append(kb_block)
    summaries = [
        component
        for component in graph.components
        if component.kind == "narrative_summary" and "llm" in component.visibility
    ]
    if summaries:
        prev_block = _block_from_components(
            prompts.get("shared.block.previous_events_summary"),
            summaries,
        )
        if prev_block:
            sections.append(prev_block)
    current = next(
        (
            component
            for component in graph.components
            if component.kind == "current_narrative" and "llm" in component.visibility
        ),
        None,
    )
    if current is not None and current.text.strip():
        cur_block = wrap_block(prompts.get("shared.block.current_passage"), current.text)
        if cur_block:
            sections.append(cur_block)
    extras = [
        component
        for component in graph.components
        if component.kind == "extra" and "llm" in component.visibility
    ]
    sections.extend(component.text for component in extras if component.text)
    state_block = _state_block_from_graph(graph, prompts)
    if state_block:
        sections.append(state_block)
    return sections


def _state_block_from_graph(graph: CrawlGraph, prompts: PromptStore) -> str:
    """Render the tail `[LIVE STATE]` block, or ``""`` when nothing is diverted.

    Callers must place this immediately before the task block in both the
    single-turn and multi-turn paths — that adjacency is the whole point of the
    divert (see :func:`_divert_state_components`).
    """
    state = [
        component
        for component in graph.components
        if component.kind == "state" and "llm" in component.visibility
    ]
    if not state:
        return ""
    return _block_from_components(prompts.get("shared.block.live_state"), state)


def crawl_result_from_pins(
    project_root: Path,
    pins: list[str],
    unpins: list[str],
    *,
    storage: Storage | None = None,
) -> CrawlResult:
    local_storage = storage or Storage(find_git_root_from(project_root))
    unpinned_bases = {u.rstrip("+").lower() for u in unpins}
    surviving_raw: list[str] = []
    seen_base: set[str] = set()
    for raw in pins:
        base = raw.rstrip("+").lower()
        if base in unpinned_bases:
            continue
        if base not in seen_base:
            seen_base.add(base)
            surviving_raw.append(raw)

    kb_store = KnowledgeStore.for_project(project_root)
    ordered_ids, objects = kb_store.get_objects_with_links(surviving_raw)
    effective_ids = [cid for cid in ordered_ids if cid.lower() not in unpinned_bases]

    knowledge_components: list[CrawlComponent] = []
    result_pinned_ids: list[str] = []
    for cid in effective_ids:
        obj = objects.get(cid) or kb_store.get_objects([cid]).get(cid)
        if obj is not None:
            normalized = local_storage.normalize_raw_text(obj.text, source_id=f"kb:{cid}")
            formatted = local_storage.format_kb_prompt_block(
                canonical_id=cid,
                text=normalized.raw_storage_text,
                tags=obj.tags,
                include_comments=False,
                source_id=f"kb:{cid}",
            )
            knowledge_components.append(
                CrawlComponent(
                    id=f"kb:{cid}",
                    kind="knowledge",
                    text=formatted,
                    source=ComponentSource(kind="knowledge", identifier=cid),
                    priority=len(knowledge_components),
                    metadata={
                        "kb_id": cid,
                        "tags": ",".join(obj.tags),
                        "expansion_policy": expansion_policy_from_tags(obj.tags).mode,
                    },
                )
            )
            result_pinned_ids.append(cid)

    remember_pins = _remember_pins_subset(project_root, result_pinned_ids)
    graph = _build_base_graph(
        project_root=project_root,
        knowledge_components=knowledge_components,
        previous_components=[],
        current_component=None,
        pinned_ids=result_pinned_ids,
        remember_pins=remember_pins,
    )
    graph = _apply_default_transforms(
        graph, project_root=project_root, storage=local_storage
    )
    return CrawlResult(
        graph,
        project_root=project_root,
        render_effects=tuple(graph.effects),
    )


def _build_kb_edit_system_prompt(
    existing_content: str | None,
    template_content: str | None,
    include_template: bool,
) -> str:
    is_new = existing_content is None
    has_template = bool(template_content and (include_template or is_new))

    if is_new:
        action = "Create text"
    else:
        action = "Edit CURRENT TEXT"

    parts = [f"{action} following the INSTRUCTIONS. "]
    if has_template:
        parts.append("Follow the structure in RESULT TEMPLATE. ")
    parts.append(
        "You have access to KB lookup tools — use them to look up "
        "existing knowledge objects before writing. "
        "Emit only the final text, no meta-commentary."
    )
    return " ".join(parts)


def assemble_prompt_kb_edit(
    result: CrawlResult,
    instruction: str,
    *,
    existing_content: str | None = None,
    template_content: str | None = None,
    include_template: bool = False,
) -> list[dict[str, str]]:
    prompts = PromptStore(result.project_root)
    is_new = existing_content is None
    extra_sections: list[str] = []
    if existing_content:
        kb_item_block = wrap_block(prompts.get("shared.block.current_text"), existing_content)
        if kb_item_block:
            extra_sections.append(kb_item_block)
    if template_content and (include_template or is_new):
        tpl_block = wrap_block(prompts.get("shared.block.result_template"), template_content)
        if tpl_block:
            extra_sections.append(tpl_block)
    system_prompt = _build_kb_edit_system_prompt(
        existing_content, template_content, include_template
    )
    graph = _prepare_render_graph(
        result,
        system_prompt=system_prompt,
        instruction=instruction,
        extra_sections=extra_sections,
    )
    result.render_graph = graph
    sections = _sections_from_graph(graph, prompts)
    task_component = next(
        (component for component in graph.components if component.kind == "task"), None
    )
    task_text = task_component.text if task_component is not None else instruction
    sections.append(wrap_block(prompts.get("shared.block.instructions"), task_text) or task_text)
    user_content = "\n\n".join(sections)
    result.render_effects = tuple(graph.effects)
    return [
        {"role": "system", "content": _system_content_from_graph(graph, prompts)},
        {"role": "user", "content": user_content},
    ]


def assemble_prompt(
    result: CrawlResult,
    *,
    system_prompt: str,
    instruction: str,
    extra_sections: list[str] | None = None,
    turns: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    prompts = PromptStore(result.project_root)
    graph = _prepare_render_graph(
        result,
        system_prompt=system_prompt,
        instruction=instruction,
        extra_sections=extra_sections,
    )
    result.render_graph = graph
    if turns:
        # The current passage is rendered as conversation turns instead of a
        # [CURRENT PASSAGE] block; explain reads this back off the graph.
        graph.metadata["rendered_as_turns"] = "true"
    system_msg = {"role": "system", "content": _system_content_from_graph(graph, prompts)}
    task_block = _task_block_from_graph(graph, prompts)

    if not turns:
        # `_sections_from_graph` already appends the state block last, so the
        # task block appended here still lands immediately after it.
        sections = _sections_from_graph(graph, prompts)
        sections.append(task_block)
        user_content = "\n\n".join(sections)
        result.render_effects = tuple(graph.effects)
        return [system_msg, {"role": "user", "content": user_content}]

    # State objects render after the last turn rather than in the prefix, so
    # they travel with the task block wherever it ends up below.
    state_block = _state_block_from_graph(graph, prompts)
    if state_block:
        task_block = f"{state_block}\n\n{task_block}"

    prefix_parts: list[str] = []
    knowledge = [
        component
        for component in graph.components
        if component.kind in {"knowledge", "reference"} and "llm" in component.visibility
    ]
    if knowledge:
        kb_block = _block_from_components(
            prompts.get("shared.block.relevant_knowledge"), knowledge
        )
        if kb_block:
            prefix_parts.append(kb_block)
    summaries = [
        component
        for component in graph.components
        if component.kind == "narrative_summary" and "llm" in component.visibility
    ]
    if summaries:
        prev_block = wrap_block(
            prompts.get("shared.block.previous_events_summary"),
            "\n\n".join(component.text for component in summaries),
        )
        if prev_block:
            prefix_parts.append(prev_block)
    prefix_parts.extend(
        component.text
        for component in graph.components
        if component.kind == "extra" and component.text and "llm" in component.visibility
    )

    turn_start = 0
    if turns[0][0] == "user":
        prefix_parts.append(turns[0][1])
        turn_start = 1

    prefix_content = "\n\n".join(p for p in prefix_parts if p)
    if not prefix_content.strip():
        prefix_content = task_block
        task_in_prefix = True
    else:
        task_in_prefix = False

    messages: list[dict[str, str]] = [system_msg, {"role": "user", "content": prefix_content}]

    remaining = turns[turn_start:]
    if not remaining:
        if not task_in_prefix:
            messages[-1]["content"] += "\n\n" + task_block
        result.render_effects = tuple(graph.effects)
        return messages

    for role, content in remaining[:-1]:
        messages.append({"role": role, "content": content})

    last_role, last_content = remaining[-1]
    if last_role == "user":
        if not task_in_prefix:
            messages.append({"role": "user", "content": last_content + "\n\n" + task_block})
        else:
            messages.append({"role": "user", "content": last_content})
    else:
        messages.append({"role": "assistant", "content": last_content})
        if not task_in_prefix:
            messages.append({"role": "user", "content": task_block})

    result.render_effects = tuple(graph.effects)
    return messages
