"""Full-text search and enumeration over the merged knowledge store.

The project's own ``knowledge/`` tree is greppable and needs no help from
Lens. The *merged* store is not: datasets resolve outside the repository
entirely (see :func:`~lens.core.project.resolve_dataset_path`), so a ``grep -r``
over a checkout silently misses every ``rules.*``, every ``design.*`` module and
every template — and grepping the trees separately yields one hit per tree with
no way to tell which one an operator would actually read.

These two commands are the entry point that was missing. :func:`kb_search`
answers "what does this project already say about grappling" for someone who
cannot guess the id; :func:`kb_list` answers "what is in here at all". Both
read :meth:`~lens.core.knowledge.KnowledgeStore.resolved_index`, so shadowing is
applied before anything is read: one hit per id, from the file that wins.

No ranking. Results come back in id order, then line order — the order an IDE
or ``grep -r`` would print them in, which is the order a reader can predict and
a pipeline can rely on.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Literal

from lens.core.commands.kb import get_store, kb_source_payload
from lens.core.exceptions import LensException
from lens.core.kb_scan import (
    FileMatches,
    build_pattern,
    pattern_flags,
    scan_files,
)
from lens.core.knowledge import KbSource, KnowledgeStore, ResolvedObject
from lens.core.storage_text import kb_headline

MatchField = Literal["id", "type", "tag", "body"]
SourceFilter = Literal["project", "dataset", "all"]

_PARALLEL_MIN_FILES = 96
"""Below this, a process pool costs more to start than the scan it would run.

A project-sized knowledge tree scans in single-digit milliseconds serially; the
pool exists for the thousand-object dataset stacks, which is where a serial
scan starts to be felt."""

_WORKERS_ENV = "LENS_KB_SEARCH_WORKERS"
"""Override the worker count. ``1`` forces the serial path (tests, profiling)."""


@dataclass(frozen=True)
class SearchMatch:
    """One matched line, or one matched piece of an object's identity."""

    field: MatchField
    line: int
    """1-based line in the object's body; ``0`` for ``id`` / ``type`` / ``tag``
    matches, which have no line of their own."""
    text: str
    context_before: list[tuple[int, str]] = dc_field(
        default_factory=list[tuple[int, str]]
    )
    context_after: list[tuple[int, str]] = dc_field(
        default_factory=list[tuple[int, str]]
    )


@dataclass(frozen=True)
class SearchHit:
    """Every match in one object, plus what it takes to decide about it."""

    id: str
    type: str
    tags: list[str]
    source: KbSource
    headline: str
    matches: list[SearchMatch]


@dataclass(frozen=True)
class SearchResult:
    pattern: str
    hits: list[SearchHit]
    scanned: int
    """Objects considered after the type/tag/source filters — the denominator
    for "3 hits" and the honest answer to "did my filter exclude everything"."""


@dataclass(frozen=True)
class KbListEntry:
    id: str
    type: str
    tags: list[str]
    source: KbSource
    headline: str


def _resolve_store(store: KnowledgeStore | None) -> KnowledgeStore:
    return store if store is not None else get_store()


def _filtered_index(
    kb: KnowledgeStore,
    *,
    type_filter: str | None,
    tags: list[str],
    source: SourceFilter,
    include_templates: bool,
) -> list[ResolvedObject]:
    """The merged store, narrowed and ordered by id.

    Tag filtering goes through :meth:`~lens.core.knowledge.KnowledgeStore.get_ids_with_tag`
    so a bare type name works as a tag here exactly as it does everywhere else,
    and repeated tags are ANDed.
    """
    index = kb.resolved_index(type_filter, include_templates)
    if tags:
        allowed = set(kb.get_ids_with_tag_groups([[tag] for tag in tags]))
        index = {cid: entry for cid, entry in index.items() if cid in allowed}
    if source != "all":
        index = {
            cid: entry for cid, entry in index.items() if entry.source.kind == source
        }
    return [index[cid] for cid in sorted(index)]


def _worker_count(file_count: int) -> int:
    """How many processes to scan *file_count* files with; 1 means stay serial."""
    override = os.environ.get(_WORKERS_ENV)
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    if file_count < _PARALLEL_MIN_FILES:
        return 1
    return max(1, min(os.cpu_count() or 1, 16))


def _scan_bodies(
    entries: list[ResolvedObject], source: str, flags: int, context: int
) -> dict[str, FileMatches]:
    """Body matches per id, fanned across processes when there is enough to do.

    Regex matching holds the GIL, so threads would not help; processes do. The
    fallback is not defensive noise — a sandboxed or fork-hostile environment
    raises on pool creation, and a search is not the place to make the user care
    about that.
    """
    specs = [(entry.id, str(entry.path)) for entry in entries]
    workers = _worker_count(len(specs))
    if workers > 1:
        chunk_size = max(1, len(specs) // (workers * 4))
        chunks = [
            specs[i : i + chunk_size] for i in range(0, len(specs), chunk_size)
        ]
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                results = list(
                    pool.map(
                        scan_files,
                        chunks,
                        [source] * len(chunks),
                        [flags] * len(chunks),
                        [context] * len(chunks),
                    )
                )
            return {found[0]: found for chunk in results for found in chunk}
        except (OSError, ValueError, ImportError, NotImplementedError):
            pass
    return {found[0]: found for found in scan_files(specs, source, flags, context)}


def _identity_matches(
    entry: ResolvedObject, tags: list[str], pattern: re.Pattern[str]
) -> list[SearchMatch]:
    """Matches on what an object *is* rather than what it says.

    An id match subsumes a type match — the type is the id's prefix — so the
    type is only reported when the id itself did not match, which keeps
    ``kb search rules`` from printing the same news twice per object.
    """
    matches: list[SearchMatch] = []
    if pattern.search(entry.id):
        matches.append(SearchMatch(field="id", line=0, text=entry.id))
    elif pattern.search(entry.type):
        matches.append(SearchMatch(field="type", line=0, text=entry.type))
    for tag in tags:
        if pattern.search(tag):
            matches.append(SearchMatch(field="tag", line=0, text=tag))
    return matches


def _body_matches(found: FileMatches | None, context: int) -> list[SearchMatch]:
    if found is None:
        return []
    _cid, matched_lines, line_texts = found
    matched_set = set(matched_lines)
    out: list[SearchMatch] = []
    for lineno in matched_lines:
        before = [
            (n, line_texts[n])
            for n in range(max(1, lineno - context), lineno)
            if n in line_texts and n not in matched_set
        ]
        after = [
            (n, line_texts[n])
            for n in range(lineno + 1, lineno + context + 1)
            if n in line_texts and n not in matched_set
        ]
        out.append(
            SearchMatch(
                field="body",
                line=lineno,
                text=line_texts.get(lineno, ""),
                context_before=before,
                context_after=after,
            )
        )
    return out


def kb_search(
    pattern: str,
    *,
    ignore_case: bool = False,
    fixed_string: bool = False,
    word: bool = False,
    type_filter: str | None = None,
    tags: list[str] | None = None,
    context: int = 0,
    source: SourceFilter = "all",
    include_templates: bool = False,
    headlines: bool = False,
    store: KnowledgeStore | None = None,
) -> SearchResult:
    """Regex over the ids, types, tags and bodies of the merged store.

    *headlines* reads the first three lines of each hit, which costs a second
    pass over the matched bodies only — off by default because the ``id:line:text``
    output does not use them.
    """
    if not pattern:
        raise LensException("a search pattern is required")
    source_re = build_pattern(pattern, fixed_string=fixed_string, word=word)
    flags = pattern_flags(ignore_case=ignore_case)
    try:
        compiled = re.compile(source_re, flags)
    except re.error as e:
        raise LensException(f"invalid pattern {pattern!r}: {e}") from e

    kb = _resolve_store(store)
    entries = _filtered_index(
        kb,
        type_filter=type_filter,
        tags=list(tags or []),
        source=source,
        include_templates=include_templates,
    )
    body_hits = _scan_bodies(entries, source_re, flags, context)

    hits: list[SearchHit] = []
    for entry in entries:
        obj_tags = kb.get_tags(entry.id)
        matches = _identity_matches(entry, obj_tags, compiled)
        matches.extend(_body_matches(body_hits.get(entry.id), context))
        if not matches:
            continue
        headline = ""
        if headlines:
            try:
                headline = kb_headline(entry.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                headline = ""
        hits.append(
            SearchHit(
                id=entry.id,
                type=entry.type,
                tags=obj_tags,
                source=entry.source,
                headline=headline,
                matches=matches,
            )
        )
    return SearchResult(pattern=pattern, hits=hits, scanned=len(entries))


def kb_list(
    *,
    type_filter: str | None = None,
    tags: list[str] | None = None,
    source: SourceFilter = "all",
    shadowed: bool = False,
    include_templates: bool = False,
    headlines: bool = True,
    store: KnowledgeStore | None = None,
) -> list[KbListEntry]:
    """Enumerate the merged store, id order.

    *shadowed* keeps only ids whose resolution overrides a copy in another
    store — the copy-on-write forks and the dataset-over-dataset overrides,
    which are otherwise invisible until someone wonders why an edit had no
    effect. Combine with *source* to ask which side did the overriding.

    *headlines* reads one body per entry; a caller printing ids only should
    turn it off rather than pay for text it will discard.
    """
    kb = _resolve_store(store)
    entries = _filtered_index(
        kb,
        type_filter=type_filter,
        tags=list(tags or []),
        source=source,
        include_templates=include_templates,
    )
    out: list[KbListEntry] = []
    for entry in entries:
        if shadowed and not entry.source.shadows:
            continue
        headline = ""
        if headlines:
            try:
                headline = kb_headline(entry.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                headline = ""
        out.append(
            KbListEntry(
                id=entry.id,
                type=entry.type,
                tags=kb.get_tags(entry.id),
                source=entry.source,
                headline=headline,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Rendering — shared by the CLI and any other caller, so the shapes cannot drift
# ---------------------------------------------------------------------------


def format_match_line(hit: SearchHit, match: SearchMatch) -> str:
    """One ``id:line:text`` line, grep-shaped so it pipes into what agents use.

    Identity matches have no line of their own, so they report line ``0`` and
    label the field they matched — the alternative, silently attributing them to
    line 1, would make ``cut -d: -f2`` lie.
    """
    if match.field == "body":
        return f"{hit.id}:{match.line}:{match.text}"
    return f"{hit.id}:0:[{match.field}] {match.text}"


def format_context_line(hit: SearchHit, lineno: int, text: str) -> str:
    """A context line, ``-``-separated the way grep separates its own."""
    return f"{hit.id}-{lineno}-{text}"


def format_hit_lines(hit: SearchHit) -> list[str]:
    """Every line one object contributes to the text output, in reading order.

    Context is carried per match, so two matches close together each claim the
    lines between them. Rendering match by match would then print a later
    context line before an earlier match — so the matches are merged into one
    line-ordered set first, with each line emitted once, and ``--`` marking a
    gap the way grep marks one between non-adjacent groups.
    """
    out: list[str] = [
        format_match_line(hit, match) for match in hit.matches if match.field != "body"
    ]
    body: dict[int, str] = {}
    matched: set[int] = set()
    for match in hit.matches:
        if match.field != "body":
            continue
        body[match.line] = format_match_line(hit, match)
        matched.add(match.line)
        for lineno, text in (*match.context_before, *match.context_after):
            body.setdefault(lineno, format_context_line(hit, lineno, text))

    previous: int | None = None
    for lineno in sorted(body):
        if previous is not None and lineno > previous + 1:
            out.append("--")
        out.append(body[lineno])
        previous = lineno
    return out


def search_payload(result: SearchResult) -> dict[str, Any]:
    """``lens kb search --json`` body."""
    return {
        "pattern": result.pattern,
        "scanned": result.scanned,
        "count": len(result.hits),
        "items": [
            {
                "id": hit.id,
                "type": hit.type,
                "tags": list(hit.tags),
                "source": kb_source_payload(hit.source),
                "headline": hit.headline,
                "matches": [
                    {
                        "field": match.field,
                        "line": match.line,
                        "text": match.text,
                        "context_before": [
                            {"line": n, "text": t} for n, t in match.context_before
                        ],
                        "context_after": [
                            {"line": n, "text": t} for n, t in match.context_after
                        ],
                    }
                    for match in hit.matches
                ],
            }
            for hit in result.hits
        ],
    }


def list_payload(entries: list[KbListEntry]) -> dict[str, Any]:
    """``lens kb list --json`` body."""
    return {
        "ids": [entry.id for entry in entries],
        "items": [
            {
                "id": entry.id,
                "type": entry.type,
                "tags": list(entry.tags),
                "source": kb_source_payload(entry.source),
                "headline": entry.headline,
            }
            for entry in entries
        ],
    }
