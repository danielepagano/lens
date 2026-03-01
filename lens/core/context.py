"""Context-aware crawl and prompt assembly for operators."""

from __future__ import annotations

from dataclasses import dataclass
from lens.core.annotations import decode_ai_secrets, strip_markdown_comments
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.pinning import KB_PIN, KB_UNPIN

SYSTEM_PROMPT_FORMATTING_ADDENDUM = (
    "\nFORMATTING: you must emit valid Markdown, but do not emit headers as you are inserting a fragment in a document. "
    "You are allowed to emit HTML comments (<!-- ai: text -->) (starting with ai: is a courtesy annotation); "
    "these will not be rendered in the Markdown output, but WILL visible to user in edit mode. Use HTML comments for storing intermediate thinking if needed. "
    "You can also emit comments that will be encoded and not readable by the user, but WILL be visible to future AI calls, these have the format "
    " <!-- ai:secret: text --> (multi-line text is also allowed). Use the ai:secret: marker to hide secrets that may be more interesting to reveal later in the story.\n"
)

@dataclass
class CrawlResult:
    knowledge: list[str]
    previous_summaries: list[str]
    current_content: str | None


def _block(title: str, body: str) -> str:
    body_stripped = body.strip()
    if not body_stripped:
        return ""
    return f"--- BEGIN {title} ---\n{body_stripped}\n--- END {title} ---"


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


def crawl(
    node: NarrativeNode,
    *,
    extra_pins: list[str] | None = None,
    extra_unpins: list[str] | None = None,
    include_kb: bool = True,
    include_narrative: bool = True,
) -> CrawlResult:
    project_root = node.narrative_root.parent.parent
    kb_store = KnowledgeStore.for_project(project_root)
    ancestors = _ancestor_chain(node)
    max_level = len(ancestors) - 1

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
            unpin_levels.setdefault(kid.rstrip("!"), set()).add(level)

    extra_level = max_level + 1
    for kid in extra_pins or []:
        all_pins.append((extra_level, kid))
    for kid in extra_unpins or []:
        base = kid.rstrip("!")
        unpin_levels.setdefault(base, set()).add(extra_level)

    def pin_survives(level: int, raw_id: str) -> bool:
        base = raw_id.rstrip("!")
        unpins = unpin_levels.get(base, set())
        return not any(u >= level for u in unpins)

    surviving: list[tuple[int, str]] = [
        (lev, raw) for lev, raw in all_pins if pin_survives(lev, raw)
    ]
    surviving.sort(key=lambda x: x[0])
    seen_base: set[str] = set()
    ordered_base: list[tuple[int, str]] = []
    for lev, raw in surviving:
        base = raw.rstrip("!")
        if base not in seen_base:
            seen_base.add(base)
            ordered_base.append((lev, raw))

    all_unpinned: set[str] = set(unpin_levels.keys())

    knowledge_formatted: list[str] = []
    if include_kb:
        effective_ids: list[str] = []
        for _lev, raw in ordered_base:
            base = raw.rstrip("!")
            if not raw.endswith("!"):
                effective_ids.append(base)
            else:
                ordered_sub, objects = kb_store.get_objects_with_links([base + "!"])
                for cid in ordered_sub:
                    if cid not in all_unpinned:
                        effective_ids.append(cid)
                for cid in objects:
                    if cid not in all_unpinned and cid not in effective_ids:
                        effective_ids.append(cid)

        for cid in effective_ids:
            obj = kb_store.get_objects([cid]).get(cid)
            if obj is not None:
                knowledge_formatted.append(obj.format(include_comments=False))

    previous_summaries: list[str] = []
    current_content: str | None = None
    if include_narrative:
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
    )


def assemble_prompt(
    result: CrawlResult,
    *,
    system_prompt: str,
    instruction: str,
    extra_sections: list[str] | None = None,
) -> list[dict[str, str]]:
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
    if extra_sections:
        sections.extend(extra_sections)
    task_block = _block("TASK", instruction)
    sections.append(task_block or instruction)
    user_content = decode_ai_secrets("\n\n".join(sections))

    return [
        {"role": "system", "content": system_prompt + SYSTEM_PROMPT_FORMATTING_ADDENDUM},
        {"role": "user", "content": user_content},
    ]
