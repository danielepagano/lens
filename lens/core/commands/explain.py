"""Core implementation of ``lens explain`` — what is in the prompt, and why.

Lens' thesis is that curated pins beat retrieval; this command makes the
curation visible.  It assembles the prompt for a cursor *exactly* as the
operator would (same crawl spec, same modality pins, same render transforms)
and then, instead of calling a model, reports every component with its size,
the block it lands in, and why it is there.

Read-only by construction: the ``Storage`` is created with ``owner=None`` and
never written to, so running explain never opens a transaction, and it needs
no LLM configuration because no model call is made.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lens.core.address import NarrativeAddress
from lens.core.annotations import decode_ai_secrets
from lens.core.mount_embed_strip import strip_standalone_lens_mount_attachment_lines
from lens.core.context import (
    BLOCK_CURRENT,
    BLOCK_EXTRA,
    BLOCK_KNOWLEDGE,
    BLOCK_PREVIOUS,
    BLOCK_STATE,
    BLOCK_SYSTEM,
    BLOCK_TASK,
    CrawlResult,
    prompt_block_for_component,
    wrap_block,
)
from lens.core.crawl_graph import CrawlComponent, CrawlGraph
from lens.core.exceptions import LensException
from lens.core.mentions import MENTION_KINDS
from lens.core.narrative import NarrativeNode
from lens.core.operator import Operator
from lens.core.operator_detect import detect_operator_name
from lens.core.operator_params import collect_merged_raw
from lens.core.operators import get_operator_class_for_name
from lens.core.project import (
    ProjectSession,
    get_selected_datasets,
    resolve_address,
    unknown_node_hint,
)
from lens.core.prompts import PromptStore

BLOCK_CONVERSATION = "conversation"

DEFAULT_CHARS_PER_TOKEN = 4
"""Rough divisor for the token estimate.

Tokenization is model-dependent and Lens does not ship a tokenizer, so this
is a documented approximation rather than a measurement.  Byte counts are
exact; token counts are ``ceil(chars / chars_per_token)``.
"""

FALLBACK_OPERATOR = "write"

SORT_ORDER = "order"
SORT_SIZE = "size"
SORT_ID = "id"
SORT_CHOICES: tuple[str, ...] = (SORT_ORDER, SORT_SIZE, SORT_ID)

_CACHE_PREFIX = "prefix"
_CACHE_VOLATILE = "volatile"

_BLOCK_CACHE: dict[str, str] = {
    BLOCK_SYSTEM: _CACHE_PREFIX,
    BLOCK_KNOWLEDGE: _CACHE_PREFIX,
    BLOCK_PREVIOUS: _CACHE_PREFIX,
    BLOCK_CURRENT: _CACHE_VOLATILE,
    BLOCK_CONVERSATION: _CACHE_VOLATILE,
    BLOCK_EXTRA: _CACHE_VOLATILE,
    BLOCK_STATE: _CACHE_VOLATILE,
    BLOCK_TASK: _CACHE_VOLATILE,
}

_BLOCK_ORDER: tuple[str, ...] = (
    BLOCK_SYSTEM,
    BLOCK_KNOWLEDGE,
    BLOCK_PREVIOUS,
    BLOCK_CURRENT,
    BLOCK_CONVERSATION,
    BLOCK_EXTRA,
    BLOCK_STATE,
    BLOCK_TASK,
)

_BLOCK_ROLE: dict[str, str] = {
    BLOCK_SYSTEM: "system",
    BLOCK_KNOWLEDGE: "user",
    BLOCK_PREVIOUS: "user",
    BLOCK_CURRENT: "user",
    BLOCK_CONVERSATION: "user/assistant",
    BLOCK_EXTRA: "user",
    BLOCK_STATE: "user",
    BLOCK_TASK: "user",
}

_BLOCK_TITLE_KEY: dict[str, str] = {
    BLOCK_KNOWLEDGE: "shared.block.relevant_knowledge",
    BLOCK_PREVIOUS: "shared.block.previous_events_summary",
    BLOCK_CURRENT: "shared.block.current_passage",
    BLOCK_STATE: "shared.block.live_state",
    BLOCK_TASK: "shared.block.task",
}


def _empty_detail() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class ExplainComponent:
    """One measured unit of the assembled prompt."""

    id: str
    kind: str
    block: str
    order: int
    bytes: int
    tokens: int
    percent: float
    provenance: str
    provenance_kind: str
    cache: str
    detail: dict[str, str] = field(default_factory=_empty_detail)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "block": self.block,
            "order": self.order,
            "bytes": self.bytes,
            "tokens": self.tokens,
            "percent": round(self.percent, 2),
            "provenance": self.provenance,
            "provenance_kind": self.provenance_kind,
            "cache": self.cache,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class ExplainBlock:
    """A rendered prompt block plus the components inside it."""

    id: str
    label: str
    role: str
    order: int
    components: tuple[ExplainComponent, ...]
    bytes: int
    tokens: int
    percent: float
    framing_bytes: int
    framing_tokens: int
    cache: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "order": self.order,
            "bytes": self.bytes,
            "tokens": self.tokens,
            "percent": round(self.percent, 2),
            "framing_bytes": self.framing_bytes,
            "framing_tokens": self.framing_tokens,
            "cache": self.cache,
            "components": [c.to_dict() for c in self.components],
        }


@dataclass(frozen=True)
class ExplainInPlace:
    """One include/mention expanded inside the passage.

    Not a block row: the block is spliced into the narrative text, so its bytes
    are already counted in ``current_passage`` / ``conversation``.  Listed
    separately because otherwise there is no way to tell from the report that a
    mention took effect at all — which is the first thing you want to know
    after writing one.
    """

    kind: str
    kb_id: str
    bytes: int
    tokens: int
    text: str = ""
    """The rendered block, used to locate it inside the passage.  Not serialised
    — consumers get the bytes and the id, and the text is already in the row."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "kb_id": self.kb_id,
            "bytes": self.bytes,
            "tokens": self.tokens,
        }


@dataclass(frozen=True)
class ExplainReport:
    """Full composition report for one cursor + operator pair."""

    address: str
    node: str
    operator: str
    line: int | None
    blocks: tuple[ExplainBlock, ...]
    excluded: tuple[ExplainComponent, ...]
    total_bytes: int
    total_tokens: int
    accounted_bytes: int
    other_bytes: int
    other_tokens: int
    message_count: int
    message_bytes: tuple[int, ...]
    chars_per_token: int
    active_modalities: tuple[str, ...]
    pinned_ids: tuple[str, ...]
    in_place: tuple[ExplainInPlace, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "node": self.node,
            "operator": self.operator,
            "line": self.line,
            "blocks": [b.to_dict() for b in self.blocks],
            "excluded": [c.to_dict() for c in self.excluded],
            "totals": {
                "bytes": self.total_bytes,
                "tokens": self.total_tokens,
                "accounted_bytes": self.accounted_bytes,
                "other_bytes": self.other_bytes,
                "other_tokens": self.other_tokens,
                "messages": self.message_count,
                "message_bytes": list(self.message_bytes),
            },
            "chars_per_token": self.chars_per_token,
            "active_modalities": list(self.active_modalities),
            "pinned_ids": list(self.pinned_ids),
            "in_place": [i.to_dict() for i in self.in_place],
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def estimate_tokens(text: str, chars_per_token: int) -> int:
    """Rough token estimate: ``ceil(len(text) / chars_per_token)``."""
    if not text:
        return 0
    divisor = max(1, chars_per_token)
    return -(-len(text) // divisor)


def _byte_size(text: str) -> int:
    return len(text.encode("utf-8"))


def _framing_size(
    rendered: str, parts: list[str], chars_per_token: int
) -> tuple[int, int]:
    """Size of what a block adds around its components.

    That is the ``--- begin/end <title> ---`` wrapper plus the separators
    between components.  Measured as the residual between the rendered block
    and its parts, so the component rows plus framing always reconstruct the
    block exactly.  The residual can go slightly negative when the block
    strips whitespace the components carried, hence the clamp.
    """
    framing_bytes = _byte_size(rendered) - sum(_byte_size(p) for p in parts)
    framing_chars = max(0, len(rendered) - sum(len(p) for p in parts))
    divisor = max(1, chars_per_token)
    return framing_bytes, -(-framing_chars // divisor)


# ---------------------------------------------------------------------------
# Target + operator resolution
# ---------------------------------------------------------------------------


def _resolve_target(
    session: ProjectSession, address: str | None, line: int | None
) -> tuple[NarrativeNode, str, int | None]:
    """Resolve *address* (or the cursor) to a node, its address string, and a line."""
    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative (run 'lens use <slug>' first)")

    if address is None:
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


def _resolve_operator(
    project_root: Path,
    node: NarrativeNode,
    requested: str | None,
    warnings: list[str],
) -> type[Operator]:
    name = requested or detect_operator_name(node) or FALLBACK_OPERATOR
    op_cls = get_operator_class_for_name(name)
    if op_cls is None:
        if requested is not None:
            raise LensException(f"unknown operator: {requested}")
        warnings.append(
            f"operator {name!r} detected at the cursor is not a known operator; "
            f"assembled as {FALLBACK_OPERATOR!r} instead"
        )
        op_cls = get_operator_class_for_name(FALLBACK_OPERATOR)
        if op_cls is None:  # pragma: no cover - write always resolves
            raise LensException(f"operator {FALLBACK_OPERATOR!r} is unavailable")
    gate = list(getattr(op_cls, "limited_to_datasets", []))
    if gate:
        active = set(get_selected_datasets(project_root))
        if not active.intersection(gate):
            warnings.append(
                f"operator {op_cls.name!r} requires one of these datasets: "
                f"{', '.join(sorted(gate))} — none is active, so the report may "
                "differ from a real run"
            )
    return op_cls


def _current_passage_override(node: NarrativeNode, line: int) -> str:
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


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _modality_pin_owners(crawl_result: CrawlResult) -> dict[str, str]:
    """Map ``kb id -> modality id`` for pins contributed by active modalities."""
    resolved = crawl_result.modality_resolution
    ctx = crawl_result.modality_context
    if resolved is None or ctx is None:
        return {}
    from lens.core.modalities.apply import modalities_for_resolution

    owners: dict[str, str] = {}
    for mod in modalities_for_resolution(resolved):
        for pin in mod.crawl_contributions(ctx).extra_pins:
            owners.setdefault(pin.rstrip("+").lower(), mod.id)
    return owners


def component_provenance(
    component: CrawlComponent,
    *,
    operator_name: str,
    modality_pins: dict[str, str],
) -> tuple[str, str, dict[str, str]]:
    """Return ``(provenance kind, human explanation, detail)`` for a component.

    The provenance kind is machine-readable (``node_pin``, ``expansion``,
    ``facet``, ``mention``, ``rules_companion``, ``module``, ``modality``,
    ``narrative``, ``operator``, …); the explanation is the sentence a human
    reads.
    """
    meta = component.metadata
    detail: dict[str, str] = {k: v for k, v in meta.items() if v}
    cid = component.id
    kb_id = meta.get("kb_id", "")

    if cid == "render-system":
        return "operator", f"{operator_name} system prompt", detail
    if cid == "render-task":
        return "operator", f"{operator_name} instruction", detail
    if cid.startswith("render-extra"):
        return "operator", f"{operator_name} extra section", detail
    if cid == "current-override":
        return "operator", "current passage override", detail

    if cid.startswith("mention-kb:"):
        # The only mentions that reach the graph: `state`-tagged objects, which
        # are diverted to the tail instead of expanding inside the passage.
        # Ordinary ones are counted where they land, in the narrative rows.
        return "mention", f"{kb_id} mentioned here (live state, sent at the tail)", detail
    if cid.startswith("mention-ref:"):
        origin = meta.get("expanded_from", "?")
        return "mention", f"@node-slice mentioned in {origin}", detail
    if cid.startswith("rules-companion:"):
        return (
            "rules_companion",
            f"rules companion auto-added for pinned {kb_id.split('.', 1)[-1]}.* objects",
            detail,
        )
    if cid.startswith("module:"):
        role = meta.get("module_role", "module")
        linked_from = meta.get("module_linked_from")
        if linked_from:
            return "module", f"'+' expansion of session module {linked_from}", detail
        return "module", f"session {role}: {kb_id}", detail

    if cid.startswith("kb:"):
        expanded_from = meta.get("pin_expanded_from")
        facet_of = meta.get("facet_of")
        pin_node = meta.get("pin_node")
        owner = modality_pins.get(kb_id.lower())
        if facet_of:
            # A facet carries its parent's pin origin, so without this branch it
            # would report as an ordinary `kb_pin` and read as something the
            # user pinned by hand.
            where = f" (pinned on {pin_node})" if pin_node else ""
            return "facet", f"'-' facet of {facet_of}{where}", detail
        if expanded_from:
            where = f" (pinned on {pin_node})" if pin_node else ""
            return "expansion", f"'+' expansion of {expanded_from}{where}", detail
        if meta.get("pin_source") == "node" and pin_node:
            return "node_pin", f"kb_pin on {pin_node}", detail
        if owner:
            return "modality", f"pinned by the {owner} modality", detail
        return "operator_pin", f"pinned by {operator_name}", detail

    if component.kind == "narrative_summary":
        return "narrative", f"ancestor summary: {meta.get('node', '?')}", detail
    if component.kind == "current_narrative":
        return "narrative", f"cursor node: {meta.get('node', '?')}", detail
    if component.kind == "warning":
        return "warning", component.text, detail
    if component.kind == "participant":
        return "participant", f"{meta.get('role', '?')} = {meta.get('kb_id', '?')}", detail

    source = component.source
    if source is not None:
        return source.kind, f"{source.kind}: {source.identifier}", detail
    return "unknown", "", detail


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _block_rendered_text(
    block_id: str, texts: list[str], prompts: PromptStore
) -> str:
    """Reproduce exactly what a block contributes to the assembled messages."""
    if not texts:
        return ""
    if block_id == BLOCK_SYSTEM:
        return "".join(texts)
    if block_id in (BLOCK_EXTRA, BLOCK_CONVERSATION):
        return "\n\n".join(texts)
    title_key = _BLOCK_TITLE_KEY.get(block_id)
    body = "\n\n".join(texts)
    if title_key is None:
        return body
    return wrap_block(prompts.get(title_key), body) or body


def _turn_components(
    operator: Operator, crawl_result: CrawlResult
) -> list[tuple[str, str]]:
    """Re-derive the conversation turns the operator's prompt would use.

    Through ``passage_view``, not a fresh read of the file: the operator sees
    the node with live mentions expanded in place, and a report that re-parsed
    the raw text would under-count every mention's bytes.
    """
    from lens.core.turns import parse_passage_turns

    node = crawl_result.current_node
    if node is None or not node.exists():
        return []
    return parse_passage_turns(operator.passage_view(crawl_result, node))


def _sorted(
    components: list[ExplainComponent], sort: str
) -> tuple[ExplainComponent, ...]:
    if sort == SORT_SIZE:
        return tuple(sorted(components, key=lambda c: (-c.bytes, c.id)))
    if sort == SORT_ID:
        return tuple(sorted(components, key=lambda c: c.id))
    return tuple(components)


def _grouped_components(graph: CrawlGraph) -> dict[str, list[CrawlComponent]]:
    """Group LLM-visible components by the block they render into.

    Only the first ``current_narrative`` is rendered (``_sections_from_graph``
    picks one); later ones are treated as excluded.
    """
    grouped: dict[str, list[CrawlComponent]] = {}
    seen_current = False
    for component in graph.components:
        block = prompt_block_for_component(component)
        if block is None:
            continue
        if block == BLOCK_CURRENT:
            if seen_current or not component.text.strip():
                continue
            seen_current = True
        grouped.setdefault(block, []).append(component)
    return grouped


def explain_context(
    session: ProjectSession,
    *,
    address: str | None = None,
    line: int | None = None,
    operator: str | None = None,
    prompt: str | None = None,
    sort: str = SORT_ORDER,
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> ExplainReport:
    """Assemble the prompt at a cursor and report its composition.

    *address* defaults to the current cursor; *line* (or an ``@line`` suffix on
    the address) reports the prompt as of that point in the node.  *operator*
    forces a specific operator instead of the one detected at the cursor —
    auto-pins and required modalities differ per operator, so the report does
    too.  Nothing is written and no model is called.
    """
    if sort not in SORT_CHOICES:
        raise LensException(
            f"unknown sort: {sort} (choose from {', '.join(SORT_CHOICES)})"
        )

    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative (run 'lens use <slug>' first)")

    warnings: list[str] = []
    node, address_str, effective_line = _resolve_target(session, address, line)
    op_cls = _resolve_operator(session.project_root, node, operator, warnings)

    storage = session.new_storage(owner=None)
    params: dict[str, Any] = collect_merged_raw(session.project_root, node, op_cls.name)
    if prompt is not None:
        params["prompt"] = prompt

    spec_kwargs: dict[str, Any] = {"storage": storage}
    if effective_line is not None:
        spec_kwargs["current_passage_override"] = _current_passage_override(
            node, effective_line
        )

    spec = op_cls.crawl_spec(
        node, params, session=session, narrative=narrative, **spec_kwargs
    )
    from lens.core.context import crawl

    crawl_result = crawl(spec)
    operator_instance = op_cls(storage, narrative)
    try:
        messages = operator_instance.build_messages(
            crawl_result, params, session=session, narrative=narrative
        )
    except LensException:
        raise
    except Exception as e:  # noqa: BLE001 - diagnostics must not leak tracebacks
        raise LensException(
            f"could not assemble the {op_cls.name} prompt at {address_str}: {e}"
        ) from e

    graph = crawl_result.render_graph
    if graph is None:  # pragma: no cover - assemble_prompt always sets it
        raise LensException("prompt assembly produced no render graph")

    return _build_report(
        graph=graph,
        crawl_result=crawl_result,
        messages=messages,
        operator_instance=operator_instance,
        address_str=address_str,
        node=node,
        line=effective_line,
        sort=sort,
        chars_per_token=chars_per_token,
        warnings=warnings,
    )


@dataclass
class _BlockDraft:
    """Mutable working block, frozen into an :class:`ExplainBlock` at the end."""

    id: str
    label: str
    role: str
    rows: list[ExplainComponent]
    bytes: int
    framing_bytes: int
    framing_tokens: int
    cache: str

    def freeze(self, order: int, sort: str, pct: Callable[[int], float]) -> ExplainBlock:
        return ExplainBlock(
            id=self.id,
            label=self.label,
            role=self.role,
            order=order,
            components=_sorted(self.rows, sort),
            bytes=self.bytes,
            tokens=sum(r.tokens for r in self.rows) + self.framing_tokens,
            percent=pct(self.bytes),
            framing_bytes=self.framing_bytes,
            framing_tokens=self.framing_tokens,
            cache=self.cache,
        )


def _build_report(
    *,
    graph: CrawlGraph,
    crawl_result: CrawlResult,
    messages: list[dict[str, str]],
    operator_instance: Operator,
    address_str: str,
    node: NarrativeNode,
    line: int | None,
    sort: str,
    chars_per_token: int,
    warnings: list[str],
) -> ExplainReport:
    prompts = PromptStore(crawl_result.project_root)
    operator_name = operator_instance.name
    modality_pins = _modality_pin_owners(crawl_result)

    message_bytes = tuple(_byte_size(m.get("content", "")) for m in messages)
    total_bytes = sum(message_bytes)

    def pct(size: int) -> float:
        return (size / total_bytes * 100.0) if total_bytes else 0.0

    in_place = _expansions_for_split(graph, chars_per_token)
    grouped = _grouped_components(graph)
    rendered_as_turns = graph.metadata.get("rendered_as_turns") == "true"
    if rendered_as_turns:
        # The current passage is replaced by conversation turns; report those
        # instead so the narrative bytes are still attributed.
        grouped.pop(BLOCK_CURRENT, None)

    drafts: list[_BlockDraft] = []
    order = 0

    for block_id in _BLOCK_ORDER:
        components = grouped.get(block_id, [])
        if not components:
            continue
        rows: list[ExplainComponent] = []
        for component in components:
            prov_kind, why, detail = component_provenance(
                component, operator_name=operator_name, modality_pins=modality_pins
            )
            # A mention expanded inside the cursor passage is its own chunk of
            # the prompt; split it out so it gets a row instead of vanishing
            # into the narrative it sits in.
            segments = (
                _split_in_place(
                    component.id, component.text, why, prov_kind, detail, in_place
                )
                if component.kind == "current_narrative"
                else [_Segment(component.id, component.text, why, prov_kind, detail)]
            )
            for segment in segments:
                size = _byte_size(segment.text)
                rows.append(
                    ExplainComponent(
                        id=segment.id,
                        kind="mention" if segment.provenance_kind == "mention" else component.kind,
                        block=block_id,
                        order=order,
                        bytes=size,
                        tokens=estimate_tokens(segment.text, chars_per_token),
                        percent=pct(size),
                        provenance=segment.provenance,
                        provenance_kind=segment.provenance_kind,
                        cache=_BLOCK_CACHE.get(block_id, "unknown"),
                        detail=segment.detail,
                    )
                )
                order += 1
        rendered = _block_rendered_text(block_id, [c.text for c in components], prompts)
        # Framing is measured against the *rows*, which after an in-place split
        # are pieces of the same text — so the residual stays correct.
        framing_bytes, framing_tokens = _framing_size(
            rendered, [c.text for c in components], chars_per_token
        )
        drafts.append(
            _BlockDraft(
                id=block_id,
                label=_block_label(block_id, prompts),
                role=_BLOCK_ROLE.get(block_id, "user"),
                rows=rows,
                bytes=_byte_size(rendered),
                framing_bytes=framing_bytes,
                framing_tokens=framing_tokens,
                cache=_BLOCK_CACHE.get(block_id, "unknown"),
            )
        )

    if rendered_as_turns:
        turn_rows: list[ExplainComponent] = []
        for index, (role, content) in enumerate(
            _turn_components(operator_instance, crawl_result)
        ):
            for segment in _split_in_place(
                f"turn:{index + 1}:{role}",
                content,
                f"{role} turn parsed from {node.path_str()}",
                "narrative",
                {"role": role},
                in_place,
            ):
                size = _byte_size(segment.text)
                turn_rows.append(
                    ExplainComponent(
                        id=segment.id,
                        kind="mention" if segment.provenance_kind == "mention" else "turn",
                        block=BLOCK_CONVERSATION,
                        order=order,
                        bytes=size,
                        tokens=estimate_tokens(segment.text, chars_per_token),
                        percent=pct(size),
                        provenance=segment.provenance,
                        provenance_kind=segment.provenance_kind,
                        cache=_CACHE_VOLATILE,
                        detail=segment.detail,
                    )
                )
                order += 1
        if turn_rows:
            drafts.append(
                _BlockDraft(
                    id=BLOCK_CONVERSATION,
                    label="CONVERSATION TURNS",
                    role=_BLOCK_ROLE[BLOCK_CONVERSATION],
                    rows=turn_rows,
                    bytes=sum(r.bytes for r in turn_rows),
                    framing_bytes=0,
                    framing_tokens=0,
                    cache=_CACHE_VOLATILE,
                )
            )

    system_draft = next((d for d in drafts if d.id == BLOCK_SYSTEM), None)
    if system_draft is not None and message_bytes:
        # Modality prompt addenda are appended to the system message after
        # assembly, so they are in the messages but not in the graph.
        addendum = message_bytes[0] - system_draft.bytes
        if addendum > 0:
            system_draft.rows.append(
                ExplainComponent(
                    id="modality-addenda",
                    kind="system",
                    block=BLOCK_SYSTEM,
                    order=order,
                    bytes=addendum,
                    tokens=-(-addendum // max(1, chars_per_token)),
                    percent=pct(addendum),
                    provenance="prompt addenda from active modalities",
                    provenance_kind="modality",
                    cache=_CACHE_PREFIX,
                )
            )
            order += 1
            system_draft.bytes += addendum

    drafts.sort(key=lambda d: _BLOCK_ORDER.index(d.id))
    blocks = tuple(d.freeze(i, sort, pct) for i, d in enumerate(drafts))

    excluded: list[ExplainComponent] = []
    for component in graph.components:
        if prompt_block_for_component(component) is not None:
            continue
        prov_kind, why, detail = component_provenance(
            component, operator_name=operator_name, modality_pins=modality_pins
        )
        excluded.append(
            ExplainComponent(
                id=component.id,
                kind=component.kind,
                block="",
                order=-1,
                bytes=_byte_size(component.text),
                tokens=estimate_tokens(component.text, chars_per_token),
                percent=0.0,
                provenance=why,
                provenance_kind=prov_kind,
                cache="n/a",
                detail=detail,
            )
        )

    # Every aggregate is the sum of its parts: component → block → report.
    # Estimating the whole prompt in one go would be marginally more accurate
    # but would leave the columns not adding up, which is worse in a tool
    # whose entire job is showing where the budget went.
    accounted = sum(b.bytes for b in blocks)
    other_bytes = max(0, total_bytes - accounted)
    other_tokens = -(-other_bytes // max(1, chars_per_token))
    return ExplainReport(
        address=address_str,
        node=node.path_str(),
        operator=operator_name,
        line=line,
        blocks=blocks,
        excluded=tuple(excluded),
        total_bytes=total_bytes,
        total_tokens=sum(b.tokens for b in blocks) + other_tokens,
        accounted_bytes=accounted,
        other_bytes=other_bytes,
        other_tokens=other_tokens,
        message_count=len(messages),
        message_bytes=message_bytes,
        chars_per_token=chars_per_token,
        active_modalities=_active_modality_ids(crawl_result),
        pinned_ids=tuple(crawl_result.pinned_ids),
        in_place=_in_place_from_rows(blocks),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class _Segment:
    """One measurable piece of a narrative row."""

    id: str
    text: str
    provenance: str
    provenance_kind: str
    detail: dict[str, str]


def _split_in_place(
    row_id: str,
    text: str,
    base_provenance: str,
    base_kind: str,
    base_detail: dict[str, str],
    expansions: Sequence[ExplainInPlace],
) -> list[_Segment]:
    """Split narrative *text* into prose and the mention blocks inside it.

    An expanded include/mention is a distinct, attributable chunk of the prompt,
    so it earns its own row rather than disappearing into the turn that happens
    to contain it.  Splitting rather than adding keeps the arithmetic honest:
    the pieces still sum to the row they came from.

    The block is located by text, so the needle has to be put through the same
    transforms the passage went through or it will not be there to find: a KB
    body carrying an ``ai:secret`` block reaches the model decoded, and a
    standalone mount attachment is stripped out.  Both paths that consume this
    apply both — the narrative component via ``SecretDecodeTransform`` /
    ``StripStandaloneMountEmbedsTransform``, the turns via ``llm_view`` and
    ``parse_passage_turns`` — so one transformed needle covers them, and it is a
    no-op for an object with neither.

    Still falls back to a single prose segment when a block cannot be located;
    a report that under-attributes beats one that double-counts.
    """
    hits: list[tuple[int, ExplainInPlace, str]] = []
    for expansion in expansions:
        if not expansion.text:
            continue
        needle = strip_standalone_lens_mount_attachment_lines(
            decode_ai_secrets(expansion.text)
        )
        at = text.find(needle)
        if at >= 0:
            hits.append((at, expansion, needle))
    if not hits:
        return [_Segment(row_id, text, base_provenance, base_kind, base_detail)]

    hits.sort(key=lambda h: h[0])
    # Segments must tile *all* of `text` with no gaps: the rows are pieces of
    # one component, and dropping even the blank line between them would leave
    # the block bytes not equal to the sum of its rows.
    segments: list[_Segment] = []
    cursor = 0
    for at, expansion, needle in hits:
        if at < cursor:
            continue
        if at > cursor:
            segments.append(
                _Segment(row_id, text[cursor:at], base_provenance, base_kind, base_detail)
            )
        marker = "+" if expansion.kind == "include" else "@"
        lifetime = (
            "rest of this node" if expansion.kind == "include" else "one AI turn"
        )
        segments.append(
            _Segment(
                f"{expansion.kind}:{expansion.kb_id}",
                # The matched form, not the original: a stripped mount embed
                # makes them different lengths and the rows must still tile.
                needle,
                f"{marker}{expansion.kb_id} expanded in place, {lifetime}",
                "mention",
                {"kb_id": expansion.kb_id, "scope": expansion.kind},
            )
        )
        cursor = at + len(needle)
    if cursor < len(text):
        segments.append(
            _Segment(row_id, text[cursor:], base_provenance, base_kind, base_detail)
        )
    return _merge_blank_segments(segments)


def _merge_blank_segments(segments: list[_Segment]) -> list[_Segment]:
    """Fold whitespace-only prose into a neighbour rather than giving it a row.

    The blank line separating a mention from the prose around it is real bytes
    that have to land somewhere, but "  " is not worth a row of its own.
    """
    merged: list[_Segment] = []
    carry = ""
    for segment in segments:
        if segment.provenance_kind != "mention" and not segment.text.strip():
            if merged:
                merged[-1] = replace(merged[-1], text=merged[-1].text + segment.text)
            else:
                carry += segment.text  # nothing before it yet; hold for the next
            continue
        merged.append(
            replace(segment, text=carry + segment.text) if carry else segment
        )
        carry = ""
    if carry:  # pragma: no cover - a split always yields one mention segment
        return segments
    return merged


def _in_place_from_rows(
    blocks: Sequence[ExplainBlock],
) -> tuple[ExplainInPlace, ...]:
    """The roll-up, derived from the rows so the two can never disagree.

    Built from the finished rows rather than from the render effects: a row
    absorbs the blank line separating it from its neighbour, so measuring the
    effect independently reported a few bytes less for the same object.
    """
    return tuple(
        ExplainInPlace(
            kind=row.detail.get("scope", ""),
            kb_id=row.detail.get("kb_id", row.id),
            bytes=row.bytes,
            tokens=row.tokens,
        )
        for block in blocks
        for row in block.components
        # `provenance_kind` is also "mention" for `mention-kb:` (a state object
        # diverted to the tail) and `mention-ref:` (a node slice).  Neither is
        # spliced into the passage, and both already have a block row, so
        # selecting on them would double-list with an empty kind.
        if row.detail.get("scope") in MENTION_KINDS
    )


def _expansions_for_split(
    graph: CrawlGraph, chars_per_token: int
) -> tuple[ExplainInPlace, ...]:
    """Includes and mentions to look for inside the narrative text.

    Read off the render effects ``crawl`` records, because the expansion leaves
    no component of its own to find it by.
    """
    out: list[ExplainInPlace] = []
    for effect in graph.effects:
        if effect.kind not in ("kb-mention", "kb-include"):
            continue
        size = int(effect.result) if effect.result.isdigit() else 0
        out.append(
            ExplainInPlace(
                kind=effect.kind.removeprefix("kb-"),
                kb_id=effect.token,
                bytes=size,
                tokens=-(-size // max(1, chars_per_token)),
                text=effect.details.get("text", ""),
            )
        )
    return tuple(out)


def _active_modality_ids(crawl_result: CrawlResult) -> tuple[str, ...]:
    resolved = crawl_result.modality_resolution
    if resolved is None:
        return ()
    ids: Sequence[str] = getattr(resolved, "active_ids", ())
    return tuple(str(i) for i in ids)


def _block_label(block_id: str, prompts: PromptStore) -> str:
    title_key = _BLOCK_TITLE_KEY.get(block_id)
    if title_key is not None:
        return prompts.get(title_key)
    if block_id == BLOCK_SYSTEM:
        return "SYSTEM"
    return block_id.upper()
