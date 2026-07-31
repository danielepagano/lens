# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

"""Media search: query parsing and phrase-scored haystack matching.

Each media file is reduced, once at write time, to a single lowercase
``haystack`` string in which its metadata key/value pairs are *denormalized*
into literal text (``type:image``, ``composite/type:subject``,
``prompt:a quick brown fox``). A query is then matched against that string
as whole, delimiter-bounded spans.

The pieces, by their usual names:

* **Field flattening / term prefixing** (Lucene, Elasticsearch) — the
  ``key:value`` encoding, which lets one flat string answer "has this
  field", "has this value", and "has this field *with* this value".
* **Sequential Dependence Model** (Metzler & Croft, 2005) — scoring ordered
  contiguous runs of query words, not just single words, so a verbatim
  phrase hit beats a bag of the same words.
* **BM25F-style fielded weighting** — a run is worth more or less depending
  on whether it landed on a key, a value, or a whole ``key:value`` compound.
* **Weighted interval scheduling** — the DP in :func:`score_record` that
  picks a maximum-weight set of *non-overlapping* runs, so a 3-word phrase
  match is not also counted as its six sub-runs.

``MediaSearchIndex`` (``cache.py``) and the ``MediaService`` write paths that
keep it in sync are what make this cheap: every file's haystack and token set
is built once per write and scanned from memory, never re-derived per query
and never re-read from the mount backend.

Two accepted asymmetries, both deliberate:

* Matching is whole-word, so there is no prefix matching — ``wor`` does not
  find ``world``. The primary caller is LLM tooling issuing considered
  queries, not type-ahead.
* A multi-word value is only compound-matchable from its start:
  ``prompt:a quick`` hits ``prompt: "a quick brown fox"`` but ``prompt:fox``
  does not, because a compound has to border the ``:``. ``fox`` alone still
  matches, as free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Query model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchQuery:
    """Parsed media search query.

    ``amy! type:image! couch "brown hair" sitting`` breaks down into::

        required_terms = ("amy", "type:image")
        scoring_terms  = ("couch", "brown hair", "sitting")

    Required terms are AND-ed hard filters and contribute nothing to the
    score. Scoring terms are ranked (see :func:`score_record`); a quoted
    phrase stays one indivisible unit.
    """

    required_terms: tuple[str, ...] = ()
    scoring_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchResult:
    """A single matching media file and its relevance score."""

    relative_path: str
    score: float


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
# Haystack construction
# ---------------------------------------------------------------------------

#: Joins one field's text to the next. A rare control character rather than
#: a space, so a phrase can never match across the seam between two
#: unrelated fields (``...color:brown hair:long...`` must not answer the
#: query ``"brown hair"``) while still matching *within* one field's own
#: space-joined value.
_HAYSTACK_SEP = "\x1f"

#: Characters allowed immediately either side of a matched span. ``.``,
#: ``_`` and ``-`` are in here because that is how filenames actually
#: separate words — ``sitting``, ``facing`` and ``jpg`` are each their own
#: word of ``sitting-facing.jpg``, as are ``portrait`` and ``rogue`` of
#: ``portrait_rogue.png``. String start/end are covered by padding the
#: haystack with spaces, so no bounds-checking is needed anywhere below.
_BORDERS = frozenset({" ", ":", "/", ".", "_", "-", _HAYSTACK_SEP})

#: The subset of ``_BORDERS`` meaning "this span stands on its own" rather
#: than sitting inside surrounding ``key:value`` / path structure.
_OUTER_BORDERS = frozenset({" ", _HAYSTACK_SEP})

_SPLIT_RE = re.compile(r"[ :/._\-\x1f]+")

#: What may sit *between* two words of a multi-word run — the same
#: separators, so ``amy house office`` matches ``amy/house/office.jpg`` and
#: ``sitting facing`` matches ``sitting-facing.jpg``, each as the ordered
#: run it reads as. The sentinel is excluded (that is the whole point of
#: it) and so is ``:``, which would let a run straddle the key / value
#: divide and blur the class weighting below.
_RUN_SEP = r"[ /._\-]+"

#: The same separators, used to count a term's words and to split it for
#: matching — so ``sitting-facing``, ``sitting facing`` and ``sitting.facing``
#: are one query as far as both matching and scoring are concerned. ``:`` is
#: deliberately not a word separator: it is structure, and a compound is
#: already rewarded by its class weight rather than by its length.
_WORD_SPLIT_RE = re.compile(_RUN_SEP)

#: Fields whose values are real mount paths: ``/`` is genuine hierarchy
#: there and must survive into the haystack, so that ``amy house office``
#: matches ``amy/house/office.jpg`` as an ordered run of bounded words.
_PATH_FIELDS = frozenset({"relative_path", "name"})

#: Applied to every *other* field's value. Without it a timestamp
#: (``12:34:56``), a URL, or a prompt containing the words "style: anime"
#: would masquerade as key/value structure the file doesn't actually have.
_VALUE_TRANS = str.maketrans({":": " ", "/": " "})


def _norm_key(key: Any) -> str:
    return " ".join(str(key).lower().replace(":", " ").split())


def _norm_value(value: Any, is_path: bool) -> str:
    text = str(value).lower()
    if not is_path:
        text = text.translate(_VALUE_TRANS)
    return " ".join(text.split())


def _emit_chunks(key_path: str, value: Any, is_path: bool, out: list[str]) -> None:
    """Append the ``key:value`` chunk(s) *value* contributes under *key_path*.

    Nested dicts extend the key path with ``/`` (matching the query syntax
    for nested fields); sequences emit one chunk per item under the same
    key. A field with no value still emits a bare ``key:`` so that querying
    the key alone finds files that merely *have* it.
    """
    if isinstance(value, dict):
        if not value:
            out.append(f"{key_path}:")
            return
        for sub_key, sub_value in value.items():  # pyright: ignore[reportUnknownVariableType]
            _emit_chunks(f"{key_path}/{_norm_key(sub_key)}", sub_value, is_path, out)
    elif isinstance(value, (list, tuple, set, frozenset)):
        if not value:
            out.append(f"{key_path}:")
            return
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            _emit_chunks(key_path, item, is_path, out)
    elif value is None:
        out.append(f"{key_path}:")
    else:
        out.append(f"{key_path}:{_norm_value(value, is_path)}")


@dataclass(frozen=True, slots=True)
class SearchRecord:
    """Precomputed, cacheable search state for a single media file.

    ``flattened`` is kept because a move rebuilds the record from it (see
    ``MediaSearchIndex.rename``) — it is not consulted during scoring.

    ``haystack`` is the denormalized, lowercase, space-padded match string;
    ``tokens`` is the set of its delimiter-separated words, used as a cheap
    membership prefilter so nearly all candidate runs are rejected before
    any string search happens (see :func:`score_record`).
    """

    flattened: dict[str, Any]
    haystack: str
    tokens: frozenset[str]


def build_search_record(flattened: dict[str, Any]) -> SearchRecord:
    """Precompute a ``SearchRecord`` from a file's flattened metadata dict."""
    chunks: list[str] = []
    for key, value in flattened.items():
        norm_key = _norm_key(key)
        _emit_chunks(norm_key, value, key in _PATH_FIELDS, chunks)
    haystack = " " + _HAYSTACK_SEP.join(chunks) + " "
    tokens = frozenset(_SPLIT_RE.split(haystack)) - {""}
    return SearchRecord(flattened=flattened, haystack=haystack, tokens=tokens)


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------


def _iter_query_tokens(query_str: str) -> Iterator[tuple[str, bool]]:
    """Yield ``(text, is_required)`` for each token in *query_str*.

    A ``"`` only opens a quoted phrase at the start of a token; anywhere
    else it is an ordinary character. A single trailing ``!`` (outside or
    just after the closing quote) marks the token required.
    """
    text = query_str.lower()
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == '"':
            close = text.find('"', i + 1)
            if close == -1:
                phrase = text[i + 1 :]
                i = n
            else:
                phrase = text[i + 1 : close]
                i = close + 1
            required = i < n and text[i] == "!"
            if required:
                i += 1
            yield " ".join(phrase.split()), required
        else:
            start = i
            while i < n and not text[i].isspace():
                i += 1
            token = text[start:i]
            if token.endswith("!"):
                yield token[:-1], True
            else:
                yield token, False


def parse_query(query_str: str) -> SearchQuery:
    """Parse a raw media search string into a ``SearchQuery``.

    Token rules
    -----------
    * ``word!`` / ``"multi word"!`` → required term (the ``!`` is stripped).
      ``key:value!`` is just the required form of a compound term — that is
      the hard metadata filter.
    * ``"multi word"`` → one indivisible scoring unit.
    * anything else → a scoring term.

    Everything is lowercased. Nothing else about a term is rewritten: a
    term keeps its ``:`` and ``/`` so it can match the denormalized
    ``key:value`` and ``path/sub:value`` structure in the haystack.
    """
    required: list[str] = []
    scoring: list[str] = []
    for text, is_required in _iter_query_tokens(query_str):
        if not text:
            continue
        (required if is_required else scoring).append(text)
    return SearchQuery(required_terms=tuple(required), scoring_terms=tuple(scoring))


# ---------------------------------------------------------------------------
# Query compilation
# ---------------------------------------------------------------------------

#: Scoring units beyond this are dropped. Run generation is quadratic in the
#: unit count and every run is tested against every indexed file, so an
#: unbounded query length is a soft denial of service. Real queries are a
#: handful of words; required terms are linear and therefore uncapped.
MAX_SCORING_UNITS = 16


def _words(text: str) -> list[str]:
    return [word for word in _WORD_SPLIT_RE.split(text) if word]


def _build_pattern(text: str) -> re.Pattern[str] | None:
    """Compile *text* for multi-word matching, or ``None`` for a single word.

    Single words are matched with ``str.find``, which is faster and needs no
    pattern; only a multi-word span needs the flexible ``_RUN_SEP`` between
    its words. Compiled here, once per query, then reused across every
    indexed file.
    """
    words = _words(text)
    if len(words) < 2:
        return None
    return re.compile(_RUN_SEP.join(re.escape(word) for word in words))


@dataclass(frozen=True, slots=True)
class _QueryTerm:
    """One query unit: its literal text plus its prefilter tokens."""

    text: str
    tokens: tuple[str, ...]
    word_count: int
    pattern: re.Pattern[str] | None


@dataclass(frozen=True, slots=True)
class _QueryRun:
    """A contiguous run of scoring units, ``[start, end]`` inclusive."""

    text: str
    start: int
    end: int
    word_count: int
    pattern: re.Pattern[str] | None
    has_colon: bool


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    """A ``SearchQuery`` with its per-query work done once, not per file.

    ``runs_by_end[k]`` holds every contiguous run of scoring units ending at
    unit *k*, which is the order the weighted-interval DP consumes them in.
    """

    required: tuple[_QueryTerm, ...] = ()
    units: tuple[_QueryTerm, ...] = ()
    runs_by_end: tuple[tuple[_QueryRun, ...], ...] = ()


def _make_term(text: str) -> _QueryTerm:
    normalized = " ".join(text.lower().split())
    tokens = tuple(part for part in _SPLIT_RE.split(normalized) if part)
    return _QueryTerm(
        text=normalized,
        tokens=tokens,
        word_count=len(_words(normalized)),
        pattern=_build_pattern(normalized),
    )


def compile_query(query: SearchQuery) -> CompiledQuery:
    """Expand *query* into the form :func:`score_record` scans files with.

    Scoring units past ``MAX_SCORING_UNITS`` are dropped; see that constant.
    """
    required = tuple(_make_term(t) for t in query.required_terms if t.strip())
    units = tuple(_make_term(t) for t in query.scoring_terms if t.strip())[:MAX_SCORING_UNITS]

    runs_by_end: list[tuple[_QueryRun, ...]] = []
    for end in range(len(units)):
        ending: list[_QueryRun] = []
        for start in range(end + 1):
            span = units[start : end + 1]
            text = " ".join(u.text for u in span)
            ending.append(
                _QueryRun(
                    text=text,
                    start=start,
                    end=end,
                    word_count=sum(u.word_count for u in span),
                    pattern=_build_pattern(text),
                    has_colon=":" in text,
                )
            )
        runs_by_end.append(tuple(ending))

    return CompiledQuery(required=required, units=units, runs_by_end=tuple(runs_by_end))


# ---------------------------------------------------------------------------
# Boundary matching and class weights
# ---------------------------------------------------------------------------

#: Weight for a run that landed where a key sits. Deliberately below a
#: value's: matching the *name* of a field is weaker evidence than matching
#: its content.
KEY_WEIGHT = 0.5
#: A run immediately following a ``:`` — the file's value for some field.
VALUE_WEIGHT = 1.0
#: A run in free-text interior (e.g. mid-prompt), worth the same as a value.
PLAIN_WEIGHT = 1.0
#: A whole literal ``key:value`` hit — the strongest signal available.
COMPOUND_WEIGHT = 2.0


def _iter_bounded(
    haystack: str,
    text: str,
    pattern: re.Pattern[str] | None,
) -> Iterator[tuple[int, int]]:
    """Yield ``(start, end)`` of each occurrence sitting on delimiters.

    Only the *ends* of the span must sit on a boundary — a term with an
    internal ``:`` (``type:image``) matches as one unit. *haystack* is
    space-padded and no term starts or ends with a delimiter, so neighbour
    lookups are always in range.
    """
    if pattern is None:
        span = len(text)
        pos = haystack.find(text)
        while pos != -1:
            if haystack[pos - 1] in _BORDERS and haystack[pos + span] in _BORDERS:
                yield pos, pos + span
            pos = haystack.find(text, pos + 1)
        return
    pos = 0
    while True:
        match = pattern.search(haystack, pos)
        if match is None:
            return
        start, end = match.span()
        if haystack[start - 1] in _BORDERS and haystack[end] in _BORDERS:
            yield start, end
        # Step by one rather than to `end`: a rejected match can overlap a
        # valid one starting further in.
        pos = start + 1


def _class_weight(haystack: str, run: _QueryRun) -> float:
    """Best class weight over every bounded occurrence of *run*, else 0.

    Presence is set semantics: a run repeated within one file counts once,
    so a rambling prompt can't outrank metadata that is exactly right.
    Where occurrences differ in class, the strongest one wins.
    """
    best = 0.0
    for start, end in _iter_bounded(haystack, run.text, run.pattern):
        left = haystack[start - 1]
        right = haystack[end]
        if right == ":":
            weight = KEY_WEIGHT
        elif left == ":":
            weight = VALUE_WEIGHT
        elif run.has_colon and left in _OUTER_BORDERS and right in _OUTER_BORDERS:
            return COMPOUND_WEIGHT  # nothing outranks it; stop looking
        else:
            weight = PLAIN_WEIGHT
        if weight > best:
            best = weight
    return best


def _matches_bounded(haystack: str, term: _QueryTerm) -> bool:
    for _ in _iter_bounded(haystack, term.text, term.pattern):
        return True
    return False


def _has_tokens(record: SearchRecord, term: _QueryTerm) -> bool:
    return all(token in record.tokens for token in term.tokens)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_record(record: SearchRecord, query: CompiledQuery) -> float | None:
    """Return *record*'s relevance score, or ``None`` if it doesn't match.

    A record is disqualified when any required term is absent, or when the
    query has scoring units and none of them match at all.

    Scoring picks a **maximum-weight set of non-overlapping runs** over the
    query's unit positions — each unit may contribute to at most one
    selected run — via the standard weighted-interval-scheduling DP::

        best[k] = max( best[k-1],                             # unit k unused
                       max over i<=k of w(i,k) + best[i-1] )  # run [i..k]

    Summing every matching run instead would count a verbatim three-word
    phrase as six independent hits, and worsen quadratically with length.
    A run's weight is ``class_weight * word_count²``, so a phrase always
    beats its own decomposition without any special-casing.
    """
    for term in query.required:
        if not _has_tokens(record, term):
            return None
        if not _matches_bounded(record.haystack, term):
            return None

    unit_count = len(query.units)
    if unit_count == 0:
        return 0.0

    # Cheap set-membership prefilter: a run can only match if every word of
    # every unit it spans is somewhere in this file. `missing` is a prefix
    # count so that test is O(1) per run rather than O(words).
    missing = [0] * (unit_count + 1)
    for i, unit in enumerate(query.units):
        missing[i + 1] = missing[i] + (0 if _has_tokens(record, unit) else 1)

    best = [0.0] * (unit_count + 1)
    for end in range(unit_count):
        candidate = best[end]  # this unit contributes nothing
        for run in query.runs_by_end[end]:
            if missing[run.end + 1] - missing[run.start]:
                continue
            weight = _class_weight(record.haystack, run)
            if not weight:
                continue
            scored = weight * run.word_count * run.word_count + best[run.start]
            if scored > candidate:
                candidate = scored
        best[end + 1] = candidate

    total = best[unit_count]
    return total if total > 0 else None
