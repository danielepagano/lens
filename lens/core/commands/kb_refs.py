"""What links to a knowledge object, and what it links to.

``kb get id++`` already answers the outbound half — by dumping every linked
body, which is expensive and hard to read when the question is structural
rather than textual. And nothing answers the inbound half at all: a plain grep
for an id finds the front matters that name it literally and misses every route
that reaches it by computation — a ``+`` expansion off a neighbour, a ``-``
facet, the ``rules.<type>`` companion that every object of a type drags along,
a ``[[dataset.modules]]`` registration in a manifest that lives outside the
repository.

So the two directions answer two different questions:

``--out``  the shape around an object — what it will pull in with it.
``--in``   who pays if this is rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from lens.core.address import NarrativeAddress
from lens.core.annotations import find_front_matter_span, parse_annotations, parse_front_matter
from lens.core.commands.kb import get_store, kb_source_payload
from lens.core.exceptions import LensException
from lens.core.knowledge import KbSource, KnowledgeStore, parse_id
from lens.core.mentions import parse_mentions
from lens.core.module_requests import dataset_modules
from lens.core.pinning import KB_PIN, KB_UNPIN
from lens.core.project import find_project_root

Direction = Literal["out", "in"]


@dataclass(frozen=True)
class Ref:
    """One edge: which way it points, what kind of edge it is, and to what.

    *detail* carries the route when the edge is not literal — "via person.hero+",
    "facet of front.problem" — because that is exactly the part a grep could not
    have told you.
    """

    direction: Direction
    kind: str
    target: str
    detail: str = ""


@dataclass(frozen=True)
class RefsResult:
    id: str
    exists: bool
    source: KbSource | None
    tags: list[str]
    refs: list[Ref]

    def outgoing(self) -> list[Ref]:
        return [ref for ref in self.refs if ref.direction == "out"]

    def incoming(self) -> list[Ref]:
        return [ref for ref in self.refs if ref.direction == "in"]


def _string_list(raw: object) -> list[str]:
    """A YAML scalar or sequence as a list of strings, ignoring anything else.

    Front matter and annotation params are user-authored YAML, so both a
    ``kb_pin: person.hero`` scalar and a list are legal, and a malformed entry
    is skipped rather than raised on.
    """
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in cast(list[object], raw) if isinstance(item, str)]
    return []


def _dot_tag_ids(tags: list[str]) -> list[str]:
    """Tags that are shaped like KB ids — the outbound links of an object."""
    out: list[str] = []
    for tag in tags:
        if "." not in tag or ":" in tag:
            continue
        try:
            parse_id(tag)
        except ValueError:
            continue
        if tag.lower() not in out:
            out.append(tag.lower())
    return out


def _outgoing_refs(kb: KnowledgeStore, canonical_id: str, tags: list[str]) -> list[Ref]:
    refs: list[Ref] = []
    linked = _dot_tag_ids(tags)
    for target in linked:
        if kb.exists(target):
            refs.append(Ref(direction="out", kind="tag-link", target=target))
        else:
            refs.append(
                Ref(
                    direction="out",
                    kind="dangling-tag",
                    target=target,
                    detail="no such object",
                )
            )

    for facet_id in kb.list_facet_ids(canonical_id):
        refs.append(Ref(direction="out", kind="facet", target=facet_id))

    obj_type = canonical_id.split(".", 1)[0] if "." in canonical_id else ""
    if obj_type and obj_type != "rules":
        companion = f"rules.{obj_type}"
        if kb.exists(companion):
            refs.append(
                Ref(
                    direction="out",
                    kind="rules-companion",
                    target=companion,
                    detail=f"every {obj_type}.* in scope pulls it",
                )
            )
    template = f"{obj_type}._template" if obj_type else ""
    if template and kb.exists(template):
        refs.append(Ref(direction="out", kind="template", target=template))

    # A `+` hop is exactly the dot-tag links above, so only the extra reach of
    # `++` is worth a line of its own.
    _ordered, objects = kb.get_objects_with_links([f"{canonical_id}++"])
    deep = [
        oid
        for oid in sorted(objects)
        if oid != canonical_id.lower() and oid not in linked
    ]
    for target in deep:
        refs.append(
            Ref(direction="out", kind="hop++", target=target, detail="reached by ++ only")
        )
    return refs


def _module_refs(project_root: Path, canonical_id: str) -> list[Ref]:
    """``[[dataset.modules]]`` registrations naming this object.

    These live in a dataset's ``lens.toml``, outside the checkout entirely, so
    nothing in the project tree records that an operator may load this object
    mid-generation.
    """
    refs: list[Ref] = []
    for decl in dataset_modules(project_root):
        if decl.kb_id.lower() != canonical_id:
            continue
        operators = ", ".join(decl.operators) or "none"
        refs.append(
            Ref(
                direction="in",
                kind="module",
                target=f"dataset:{decl.dataset}",
                detail=f"loadable by {operators}",
            )
        )
    return refs


def _kb_incoming_refs(kb: KnowledgeStore, canonical_id: str) -> list[Ref]:
    refs: list[Ref] = []
    for oid in kb.get_ids_with_tag(canonical_id):
        if oid.lower() == canonical_id:
            continue
        refs.append(Ref(direction="in", kind="tag-link", target=oid))

    obj_type, _, key = canonical_id.partition(".")
    if key and "-" in key:
        # `front.problem-prep` is a facet of `front.problem`; the relationship is
        # purely lexical, so every prefix that exists is a parent.
        parts = key.split("-")
        for cut in range(1, len(parts)):
            parent = f"{obj_type}.{'-'.join(parts[:cut])}"
            if kb.exists(parent):
                refs.append(Ref(direction="in", kind="facet-of", target=parent))

    if obj_type == "rules" and key:
        of_type = kb.list_ids(type_filter=key)
        if of_type:
            refs.append(
                Ref(
                    direction="in",
                    kind="rules-companion",
                    target=f"{key}.*",
                    detail=f"{len(of_type)} object(s) pull this when in scope",
                )
            )
    return refs


def _narrative_files(project_root: Path) -> list[tuple[Path, Path]]:
    """``(narrative root, node file)`` for every node file in the project."""
    narrative_dir = project_root / "narrative"
    if not narrative_dir.is_dir():
        return []
    out: list[tuple[Path, Path]] = []
    for tree in sorted(narrative_dir.iterdir()):
        if not tree.is_dir():
            continue
        for path in sorted(tree.rglob("*.md")):
            out.append((tree, path))
    return out


def _address_for(narrative_root: Path, path: Path) -> NarrativeAddress:
    rel = path.relative_to(narrative_root)
    parts = list(rel.parts)
    if parts and parts[-1] == "_node.md":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][: -len(".md")]
    return NarrativeAddress(narrative=narrative_root.name, key_path=tuple(parts))


def _pin_route(
    kb: KnowledgeStore, raw_pin: str, canonical_id: str, cache: dict[str, str | None]
) -> str | None:
    """How *raw_pin* reaches *canonical_id*, or ``None`` if it does not.

    The literal case is one string comparison; the rest is why this function
    exists. A pin written ``person.hero+`` puts everything ``person.hero``
    dot-tags into scope, a root pin on a prep-side operator also pulls the
    pinned id's ``-`` facets, and any object of type ``T`` in scope drags
    ``rules.T`` in behind it. None of those name this object anywhere on disk.
    """
    key = f"{raw_pin}\x00{canonical_id}"
    if key in cache:
        return cache[key]
    route = _compute_pin_route(kb, raw_pin, canonical_id)
    cache[key] = route
    return route


def _compute_pin_route(
    kb: KnowledgeStore, raw_pin: str, canonical_id: str
) -> str | None:
    base = raw_pin.rstrip("+").lower()
    if not base:
        return None
    if base == canonical_id:
        return ""
    if raw_pin.endswith("+"):
        _ordered, objects = kb.get_objects_with_links([raw_pin.lower()])
        if canonical_id in objects:
            return f"via {raw_pin}"
    if canonical_id in kb.list_facet_ids(base):
        return f"facet of {base}"
    base_type = base.split(".", 1)[0]
    if canonical_id == f"rules.{base_type}":
        return f"rules companion of {base}"
    return None


def _front_matter_pin_refs(
    kb: KnowledgeStore,
    text: str,
    address: NarrativeAddress,
    canonical_id: str,
    cache: dict[str, str | None],
) -> list[Ref]:
    refs: list[Ref] = []
    fm = parse_front_matter(text)
    span = find_front_matter_span(text)
    line = (span[0] + 1) if span is not None else 1
    for field_name in (KB_PIN, KB_UNPIN):
        for entry in _string_list(fm.get(field_name)):
            route = _pin_route(kb, entry, canonical_id, cache)
            if route is None:
                continue
            detail = f"{field_name} {route}".strip()
            refs.append(
                Ref(
                    direction="in",
                    kind="narrative",
                    target=f"{address}@{line}",
                    detail=detail,
                )
            )
    return refs


def _annotation_refs(
    text: str, address: NarrativeAddress, canonical_id: str
) -> list[Ref]:
    """Mentions, includes, and session ``module:`` params naming this object.

    A ``module:`` param stores the *key*, not the id — ``[play: … module: combat]``
    means ``rules.combat`` because ``play`` prefixes with ``rules.`` — so the
    operator's own prefix is what turns the param back into an id.
    """
    from lens.core.operators import get_operator_class_for_name

    refs: list[Ref] = []
    for ref in parse_mentions(text):
        if ref.kb_id.lower() != canonical_id:
            continue
        refs.append(
            Ref(
                direction="in",
                kind="narrative",
                target=f"{address}@{ref.line}",
                detail=ref.kind,
            )
        )

    for ann in parse_annotations(text):
        if ann.closing:
            continue
        keys = _string_list(ann.params.get("module"))
        if not keys:
            continue
        op_class = get_operator_class_for_name(ann.operator)
        prefix = getattr(op_class, "module_prefix", "") if op_class else ""
        for key in keys:
            module_id = f"{prefix}{key}".lower()
            if module_id != canonical_id:
                continue
            refs.append(
                Ref(
                    direction="in",
                    kind="narrative",
                    target=f"{address}@{ann.line_start}",
                    detail=f"{ann.operator} module",
                )
            )
    return refs


def _narrative_refs(
    kb: KnowledgeStore, project_root: Path, canonical_id: str
) -> list[Ref]:
    refs: list[Ref] = []
    cache: dict[str, str | None] = {}
    for narrative_root, path in _narrative_files(project_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        address = _address_for(narrative_root, path)
        refs.extend(
            _front_matter_pin_refs(kb, text, address, canonical_id, cache)
        )
        refs.extend(_annotation_refs(text, address, canonical_id))
    return refs


def kb_refs(
    canonical_id: str,
    *,
    outgoing: bool = True,
    incoming: bool = True,
    store: KnowledgeStore | None = None,
    project_root: Path | None = None,
) -> RefsResult:
    """The links around *canonical_id*, without paying for any body but its own.

    Both directions by default; a caller normally wants one. An id that resolves
    to nothing still reports its inbound refs — a pin or a dot-tag pointing at a
    deleted object is precisely what someone auditing wants to see.
    """
    try:
        parse_id(canonical_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    cid = canonical_id.lower()
    kb = store if store is not None else get_store()
    if project_root is None:
        try:
            project_root = find_project_root()
        except RuntimeError as e:
            raise LensException(str(e)) from e

    tags = kb.get_tags(cid)
    refs: list[Ref] = []
    if outgoing:
        refs.extend(_outgoing_refs(kb, cid, tags))
    if incoming:
        refs.extend(_kb_incoming_refs(kb, cid))
        refs.extend(_module_refs(project_root, cid))
        refs.extend(_narrative_refs(kb, project_root, cid))

    return RefsResult(
        id=cid,
        exists=kb.exists(cid),
        source=kb.describe_source(cid),
        tags=tags,
        refs=refs,
    )


def format_ref_line(ref: Ref) -> str:
    """``kind  target  detail``, aligned enough to skim and stable enough to cut."""
    line = f"  {ref.kind:<16}{ref.target}"
    if ref.detail:
        line = f"{line}  ({ref.detail})"
    return line


def refs_payload(result: RefsResult) -> dict[str, Any]:
    """``lens kb refs --json`` body."""
    return {
        "id": result.id,
        "exists": result.exists,
        "source": kb_source_payload(result.source),
        "tags": list(result.tags),
        "refs": [
            {
                "direction": ref.direction,
                "kind": ref.kind,
                "target": ref.target,
                "detail": ref.detail,
            }
            for ref in result.refs
        ],
    }


__all__ = [
    "Ref",
    "RefsResult",
    "format_ref_line",
    "kb_refs",
    "refs_payload",
]
