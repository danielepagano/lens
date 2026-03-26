"""Context-aware crawl and prompt assembly for operators."""

from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass, field

from lens.core.annotations import decode_ai_secrets, strip_markdown_comments
from lens.core.knowledge import KnowledgeObject, KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.pinning import KB_PIN, KB_UNPIN

SYSTEM_PROMPT_FORMATTING_ADDENDUM = (
    "\nFORMATTING: you must emit valid Markdown, and do not emit headers as you are inserting a fragment in a document. "
    "You are allowed to emit HTML comments (<!-- ai: text -->) (starting with ai: is a courtesy annotation); "
    "these will not be rendered in the Markdown output, but WILL be visible to user in edit mode. Use HTML comments for storing intermediate thinking if needed. "
    "You can also emit comments that will be encoded and not readable by the user, but WILL be visible to future AI calls, these have the format "
    " <!-- ai:secret: text --> (multi-line text is also allowed). Use the ai:secret: marker to hide secrets that may be more interesting to reveal later in the story.\n"
)

@dataclass
class SliceAnchor:
    """A fixed point in the narrative tree from which to start collecting text.

    Used by :func:`crawl` to replace the standard ancestor-chain narrative with
    a **spine walk** from a known position to the current node.  KB pin
    resolution is always based on the full ancestor chain regardless.

    Attributes:
        node: The narrative node where the anchor lives.
        line_end: 1-based line number *after* the anchor boundary.  Text
            collection on this node starts from this line onward.
    """
    node: NarrativeNode
    line_end: int


@dataclass
class CrawlResult:
    knowledge: list[str]
    previous_summaries: list[str]
    current_content: str | None
    pinned_ids: list[str] = field(default_factory=list[str])


def _block(title: str, body: str) -> str:
    body_stripped = body.strip()
    if not body_stripped:
        return ""
    return f"--- begin {title} ---\n{body_stripped}\n--- end {title} ---"


def _ancestor_chain(node: NarrativeNode) -> list[NarrativeNode]:
    chain: list[NarrativeNode] = []
    for depth in range(len(node.key_path) + 1):
        chain.append(
            NarrativeNode(
                narrative_root=node.narrative_root,
                key_path=node.key_path[:depth],
            )
        )
    return chain


def _resolve_pins_for_ancestors(
    project_root: Path,
    ancestors: list[NarrativeNode],
    *,
    extra_pins: list[str] | None = None,
    extra_unpins: list[str] | None = None,
    include_kb: bool,
) -> tuple[list[str], list[str]]:
    """Resolve pins/unpins across *ancestors* and optional extras.

    Returns a pair ``(knowledge_formatted, pinned_ids)``. When ``include_kb`` is
    false, both lists are empty but the pin resolution (which objects survive)
    still follows the same rules as a full crawl.
    """
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
        return [], []

    knowledge_formatted: list[str] = []
    pinned_ids: list[str] = []

    effective_ids: list[str] = []
    all_objects: dict[str, KnowledgeObject] = {}
    for _lev, raw in ordered_base:
        base = raw.rstrip("+")
        if not raw.endswith("+"):
            effective_ids.append(base)
            objs = kb_store.get_objects([base])
            all_objects.update(objs)
        else:
            ordered_ids, objects = kb_store.get_objects_with_links([raw])
            for cid in ordered_ids:
                if cid not in all_unpinned and cid not in effective_ids:
                    effective_ids.append(cid)
            all_objects.update(objects)

    for cid in effective_ids:
        obj = all_objects.get(cid)
        if obj is not None:
            knowledge_formatted.append(obj.format(include_comments=False))
            pinned_ids.append(cid)

    return knowledge_formatted, pinned_ids


def spine_path(
    anchor_node: NarrativeNode, cursor_node: NarrativeNode
) -> list[NarrativeNode]:
    """Return the ordered list of nodes on the shortest path between two nodes.

    The path goes from *anchor_node* up to the lowest common ancestor, then
    down to *cursor_node*.  Both endpoints are included.  When the two nodes
    are the same, a single-element list is returned.
    """
    a_path = anchor_node.key_path
    c_path = cursor_node.key_path

    lca_depth = 0
    for i in range(min(len(a_path), len(c_path))):
        if a_path[i] == c_path[i]:
            lca_depth = i + 1
        else:
            break

    # anchor → … → LCA (ascending, inclusive)
    path: list[NarrativeNode] = []
    for depth in range(len(a_path), lca_depth - 1, -1):
        path.append(
            NarrativeNode(
                narrative_root=anchor_node.narrative_root,
                key_path=a_path[:depth],
            )
        )

    # LCA+1 → … → cursor (descending, LCA already present)
    for depth in range(lca_depth + 1, len(c_path) + 1):
        path.append(
            NarrativeNode(
                narrative_root=cursor_node.narrative_root,
                key_path=c_path[:depth],
            )
        )

    return path


def _collect_spine_narrative(
    anchor: SliceAnchor, cursor_node: NarrativeNode
) -> tuple[list[str], str | None]:
    """Collect narrative text along the spine from *anchor* to *cursor_node*.

    Returns ``(previous_summaries, current_content)`` matching the shape
    that :class:`CrawlResult` expects.  Only nodes on the spine are read;
    lateral subtrees are not descended into.

    * **Anchor node**: text starting from ``anchor.line_end`` onward.
    * **Intermediate nodes**: full text.
    * **Cursor node** (last): full text → ``current_content``.

    All collected text is run through :func:`strip_markdown_comments`.
    """
    path = spine_path(anchor.node, cursor_node)

    previous_summaries: list[str] = []
    current_content: str | None = None

    for node in path:
        if not node.exists():
            continue
        text = node.md_path().read_text(encoding="utf-8")

        # On the anchor node, skip everything before the anchor boundary.
        if node.key_path == anchor.node.key_path:
            lines = text.split("\n")
            # line_end is 1-based; convert to 0-based index for slicing.
            text = "\n".join(lines[anchor.line_end - 1 :])

        stripped = strip_markdown_comments(text).strip()
        if not stripped:
            continue

        if node.key_path == cursor_node.key_path:
            current_content = stripped
        else:
            previous_summaries.append(stripped)

    return previous_summaries, current_content


def crawl(
    node: NarrativeNode,
    *,
    extra_pins: list[str] | None = None,
    extra_unpins: list[str] | None = None,
    include_kb: bool = True,
    include_narrative: bool = True,
    anchor: SliceAnchor | None = None,
) -> CrawlResult:
    project_root = node.narrative_root.parent.parent
    ancestors = _ancestor_chain(node)

    knowledge_formatted, pinned_ids = _resolve_pins_for_ancestors(
        project_root,
        ancestors,
        extra_pins=extra_pins,
        extra_unpins=extra_unpins,
        include_kb=include_kb,
    )

    previous_summaries: list[str] = []
    current_content: str | None = None
    if include_narrative:
        if anchor is not None:
            previous_summaries, current_content = _collect_spine_narrative(
                anchor, node
            )
        else:
            for anc in ancestors[:-1]:
                if not anc.exists():
                    continue
                text = anc.md_path().read_text(encoding="utf-8")
                stripped = strip_markdown_comments(text)
                if stripped.strip():
                    previous_summaries.append(stripped.strip())
            current_node = ancestors[-1]
            if current_node.exists():
                text = current_node.md_path().read_text(encoding="utf-8")
                stripped = strip_markdown_comments(text)
                if stripped.strip():
                    current_content = stripped.strip()

    return CrawlResult(
        knowledge=knowledge_formatted,
        previous_summaries=previous_summaries,
        current_content=current_content,
        pinned_ids=pinned_ids,
    )


def crawl_pins(
    node: NarrativeNode,
    *,
    extra_pins: list[str] | None = None,
    extra_unpins: list[str] | None = None,
) -> list[str]:
    """Return the effective pinned KB IDs at *node*.

    Resolution rules (ancestor aggregation, unpins, ``+`` expansion, and
    deduplication) exactly match :func:`crawl`. Only KB items that actually
    exist in the store are returned.
    """
    project_root = node.narrative_root.parent.parent
    ancestors = _ancestor_chain(node)
    _knowledge, pinned_ids = _resolve_pins_for_ancestors(
        project_root,
        ancestors,
        extra_pins=extra_pins,
        extra_unpins=extra_unpins,
        include_kb=True,
    )
    return pinned_ids


def _sections_from_crawl_result(result: CrawlResult) -> list[str]:
    # The middle of the context receives the lowest attention, so we try to put old story there
    sections: list[str] = []
    if result.knowledge:
        kb_block = _block("RELEVANT KNOWLEDGE", "\n\n".join(result.knowledge))
        if kb_block:
            sections.append(kb_block)
    if result.previous_summaries:
        prev_block = _block(
            "PREVIOUS EVENTS SUMMARY",
            "\n\n".join(result.previous_summaries),
        )
        if prev_block:
            sections.append(prev_block)
    if result.current_content:
        cur_block = _block(
            "CURRENT PASSAGE",
            result.current_content,
        )
        if cur_block:
            sections.append(cur_block)
    return sections


def crawl_result_from_pins(
    project_root: Path,
    pins: list[str],
    unpins: list[str],
) -> CrawlResult:
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

    knowledge_formatted: list[str] = []
    result_pinned_ids: list[str] = []
    for cid in effective_ids:
        obj = objects.get(cid) or kb_store.get_objects([cid]).get(cid)
        if obj is not None:
            knowledge_formatted.append(obj.format(include_comments=False))
            result_pinned_ids.append(cid)

    return CrawlResult(
        knowledge=knowledge_formatted,
        previous_summaries=[],
        current_content=None,
        pinned_ids=result_pinned_ids,
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
    parts.append("Emit only the final text, no meta-commentary.")
    return " ".join(parts)


def assemble_prompt_kb_edit(
    result: CrawlResult,
    instruction: str,
    *,
    existing_content: str | None = None,
    template_content: str | None = None,
    include_template: bool = False,
) -> list[dict[str, str]]:
    is_new = existing_content is None
    sections = _sections_from_crawl_result(result)
    if existing_content:
        kb_item_block = _block("CURRENT TEXT", existing_content)
        if kb_item_block:
            sections.append(kb_item_block)
    if template_content and (include_template or is_new):
        tpl_block = _block("RESULT TEMPLATE", template_content)
        if tpl_block:
            sections.append(tpl_block)
    task_block = _block("INSTRUCTIONS", instruction)
    sections.append(task_block or instruction)
    user_content = decode_ai_secrets("\n\n".join(sections))

    system_prompt = _build_kb_edit_system_prompt(
        existing_content, template_content, include_template
    )
    return [
        {"role": "system", "content": system_prompt + SYSTEM_PROMPT_FORMATTING_ADDENDUM},
        {"role": "user", "content": user_content},
    ]


def assemble_prompt(
    result: CrawlResult,
    *,
    system_prompt: str,
    instruction: str,
    extra_sections: list[str] | None = None,
) -> list[dict[str, str]]:
    sections = _sections_from_crawl_result(result)
    if extra_sections:
        sections.extend(extra_sections)
    task_block = _block("TASK", instruction)
    sections.append(task_block or instruction)
    user_content = decode_ai_secrets("\n\n".join(sections))

    return [
        {"role": "system", "content": system_prompt + SYSTEM_PROMPT_FORMATTING_ADDENDUM},
        {"role": "user", "content": user_content},
    ]
