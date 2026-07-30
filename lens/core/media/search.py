# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Query model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchQuery:
    """Parsed media search query.

    ``amy! house! type:image composite/type:subject couch bed sitting laying down``
    breaks down into::

        required_terms = ("amy", "house")
        kv_pairs       = (("type", "image"),)
        nested_kv_pairs = (("composite", "type", "subject"),)
        optional_terms = ("couch", "bed", "sitting", "laying", "down")
    """

    required_terms: tuple[str, ...] = ()
    kv_pairs: tuple[tuple[str, str], ...] = ()
    nested_kv_pairs: tuple[tuple[str, str, str], ...] = ()
    optional_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchResult:
    """A single matching media file and its relevance score."""

    relative_path: str
    score: int


PAGE_SIZE = 20


@dataclass(frozen=True)
class SearchPage:
    """A paginated slice of search results."""

    items: tuple[SearchResult, ...]
    total_items: int
    total_pages: int
    page_size: int = PAGE_SIZE
    current_page: int = 1


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------


def parse_query(query_str: str) -> SearchQuery:
    """Parse a raw media search string into a ``SearchQuery``.

    Token rules
    -----------
    * ``word!``  → required term (the ``!`` is stripped).
    * ``key:value`` → top-level KV pair.
    * ``path/sub:value`` → nested KV pair (``/`` splits the navigation path
      from the terminal key).
    * ``word`` → optional term.
    """
    tokens = query_str.split()
    required: list[str] = []
    kv: list[tuple[str, str]] = []
    nested_kv: list[tuple[str, str, str]] = []
    optional: list[str] = []

    for token in tokens:
        if not token:
            continue
        if token.endswith("!"):
            required.append(token[:-1])
        elif ":" in token:
            raw_key, _, value = token.partition(":")
            if "/" in raw_key:
                path, _, subkey = raw_key.rpartition("/")
                nested_kv.append((path, subkey, value))
            else:
                kv.append((raw_key, value))
        else:
            optional.append(token)

    return SearchQuery(
        required_terms=tuple(required),
        kv_pairs=tuple(kv),
        nested_kv_pairs=tuple(nested_kv),
        optional_terms=tuple(optional),
    )


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _collect_strings(flattened: dict[str, Any]) -> list[str]:
    """Collect every string-representable leaf value from *flattened*."""
    strings: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value.lower())
        elif isinstance(value, (int, float, bool)):
            strings.append(str(value).lower())
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    _walk(flattened)
    return strings


def _matches_required(
    flattened: dict[str, Any],
    terms: tuple[str, ...],
) -> bool:
    """All required terms must appear as substrings in any string value."""
    if not terms:
        return True
    searchable = _collect_strings(flattened)
    for term in terms:
        term_lower = term.lower()
        if not any(term_lower in s for s in searchable):
            return False
    return True


def _matches_kv(
    flattened: dict[str, Any],
    kv_pairs: tuple[tuple[str, str], ...],
) -> bool:
    """All top-level KV pairs must match exactly (case-insensitive)."""
    for key, value in kv_pairs:
        actual = flattened.get(key)
        if actual is None:
            return False
        if str(actual).lower() != value.lower():
            return False
    return True


def _matches_nested_kv(
    extra: dict[str, Any],
    nested_kv_pairs: tuple[tuple[str, str, str], ...],
) -> bool:
    """All nested KV pairs must match by navigating into the extra dict.

    ``("composite", "type", "subject")`` navigates
    ``extra["composite"]["type"]`` and checks it equals ``"subject"``
    (case-insensitive).
    """
    for path, key, value in nested_kv_pairs:
        subtree: Any = extra
        if path:
            for part in path.split("/"):
                if not isinstance(subtree, dict):
                    return False
                subtree = subtree.get(part, {})
        if not isinstance(subtree, dict):
            return False
        actual = subtree.get(key)
        if actual is None:
            return False
        if str(actual).lower() != value.lower():
            return False
    return True


def _score_optional(
    flattened: dict[str, Any],
    terms: tuple[str, ...],
) -> int:
    """Count how many optional terms match as substrings."""
    if not terms:
        return 0
    searchable = _collect_strings(flattened)
    score = 0
    for term in terms:
        term_lower = term.lower()
        if any(term_lower in s for s in searchable):
            score += 1
    return score


def score_query(
    flattened: dict[str, Any],
    extra: dict[str, Any],
    query: SearchQuery,
) -> int | None:
    """Return a relevance score if *query* matches, or ``None`` if disqualified.

    A result is disqualified when:
    * Any required term is absent.
    * Any top-level KV pair does not match.
    * Any nested KV pair does not match.
    * Optional terms are present but none match.

    When all checks pass the returned score is the count of matching optional
    terms (0 if the query has no optional terms).
    """
    if not _matches_required(flattened, query.required_terms):
        return None
    if not _matches_kv(flattened, query.kv_pairs):
        return None
    if not _matches_nested_kv(extra, query.nested_kv_pairs):
        return None
    score = _score_optional(flattened, query.optional_terms)
    if query.optional_terms and score == 0:
        return None
    return score


# ---------------------------------------------------------------------------
# Precomputed search records
# ---------------------------------------------------------------------------
#
# ``score_query`` above rebuilds the searchable string list from scratch on
# every call, which is fine for a one-off check but wasteful when scanning
# many files per search. ``SearchRecord`` precomputes the searchable text
# once (at write time) as a single lowercase ``haystack`` string, joined
# with a control character that never appears in real query terms — so a
# substring check against one string replaces walking a list of strings, and
# (unlike a plain "".join) a term still can never match across the boundary
# between two unrelated field values.
#
# This is a placeholder scoring engine (plain substring matching). The
# design for its replacement — denormalized key:value phrase matching,
# boundary-delimited terms, quoted literal phrases, and weighted-interval-
# scheduling scoring so phrase hits beat their own sub-word decomposition —
# is written up on https://github.com/danielepagano/lens/issues/103.
# MediaSearchIndex (cache.py) and everything that keeps it in sync
# (MediaService in service.py) are NOT placeholders; only SearchRecord /
# build_search_record / score_record here, and parse_query's lack of quoted-
# phrase support, are in scope for that redesign.

_HAYSTACK_SEP = "\x1f"


@dataclass(frozen=True, slots=True)
class SearchRecord:
    """Precomputed, cacheable search state for a single media file.

    Deliberately holds only ``flattened`` (never a separate ``extra`` copy):
    ``flattened`` already *is* the reserved path-derived fields plus
    ``extra`` merged on top (see ``MediaMetadata.flattened()``), including
    the same nested dict objects nested KV lookups need to navigate — extra
    keys never collide with the 4 reserved names, so a second copy would add
    nothing but memory. ``haystack`` is the one field that's a genuinely
    different representation (a single precomputed lowercase string for
    substring checks, vs. ``flattened``'s exact-key-lookup shape) and the
    only thing actually expensive to keep re-deriving per query.
    """

    flattened: dict[str, Any]
    haystack: str


def build_search_record(flattened: dict[str, Any]) -> SearchRecord:
    """Precompute a ``SearchRecord`` from a file's flattened metadata dict."""
    haystack = _HAYSTACK_SEP.join(_collect_strings(flattened))
    return SearchRecord(flattened=flattened, haystack=haystack)


def _matches_required_haystack(haystack: str, terms: tuple[str, ...]) -> bool:
    if not terms:
        return True
    return all(term.lower() in haystack for term in terms)


def _score_optional_haystack(haystack: str, terms: tuple[str, ...]) -> int:
    if not terms:
        return 0
    return sum(1 for term in terms if term.lower() in haystack)


def score_record(record: SearchRecord, query: SearchQuery) -> int | None:
    """Same semantics as ``score_query``, against a precomputed ``SearchRecord``."""
    if not _matches_required_haystack(record.haystack, query.required_terms):
        return None
    if not _matches_kv(record.flattened, query.kv_pairs):
        return None
    # Nested KV paths navigate into `flattened` itself: extra's nested dicts
    # are merged into it by identity (see SearchRecord docstring), and extra
    # keys never collide with the 4 reserved top-level fields.
    if not _matches_nested_kv(record.flattened, query.nested_kv_pairs):
        return None
    score = _score_optional_haystack(record.haystack, query.optional_terms)
    if query.optional_terms and score == 0:
        return None
    return score
