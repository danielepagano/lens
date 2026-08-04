"""Facet vocabulary discovery and the ``[facets: ...]`` annotation for ``media_attach``.

A **facet** is a ``key: value`` pair under the reserved ``facets`` sidecar key
(``lens/core/media/metadata.py``). ``_emit_chunks`` (``search.py``) already
flattens ``facets: {emotion: happy}`` into the queryable chunk
``facets/emotion:happy``, so a discovered facet is directly re-usable as a
search term with no changes to search itself — see :func:`facet_query_terms`.

The annotation form (:func:`build_facets_annotation`) is a markdown
reference-style comment, not a Lens operator annotation: it parses as
*nothing* under ``lens.core.annotations`` (empty from ``parse_annotations``,
``None`` from ``find_unclosed_cursor_annotation``, stripped by
``strip_markdown_comments``), so it cannot be mistaken for an open operator
tag, cannot move the cursor, never reaches the LLM, and does not inflate
auto-compress accounting. This is why facets are written this way rather than
as an HTML comment (which *does* reach the LLM) or as an extension of the
composite embed format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, cast

FACET_KEY = "facets"


@dataclass(frozen=True)
class FacetVocabulary:
    """Facet values discovered across every record matching an anchor query."""

    match_count: int
    values: Mapping[str, frozenset[str]]

    @property
    def undecided(self) -> dict[str, frozenset[str]]:
        """Facets with more than one distinct value — the label set to classify against.

        A single-valued facet is already pinned by the anchor and needs no decision
        (issue #51, step 3 of the selection loop).
        """
        return {key: vals for key, vals in self.values.items() if len(vals) > 1}


def _collect_value(key: str, value: Any, out: dict[str, set[str]]) -> None:
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            _collect_value(key, item, out)
        return
    if value is None:
        return
    text = str(value).strip().lower()
    if not text:
        return
    out.setdefault(key, set()).add(text)


def collect_facet_values(flattened: dict[str, Any], out: dict[str, set[str]]) -> None:
    """Merge one record's ``facets`` values into *out* (mutated in place).

    Reads ``flattened.get(FACET_KEY)`` — a dict of scalars or lists, matching what
    ``_emit_chunks`` (``search.py``) flattens a sidecar ``facets:`` mapping into.
    Anything else (missing key, wrong shape) is silently ignored.
    """
    raw = flattened.get(FACET_KEY)
    if not isinstance(raw, dict):
        return
    rd = cast(dict[Any, Any], raw)
    for key_raw, value in rd.items():
        key = str(key_raw).strip().lower()
        if not key:
            continue
        _collect_value(key, value, out)


def facet_query_terms(chosen: Mapping[str, str]) -> list[str]:
    """Build unrequired ``facets/<k>:<v>`` scoring terms for the chosen facet values.

    Unrequired so they score rather than filter (``COMPOUND_WEIGHT``,
    ``search.py``) — combined with the anchor's required (``!``) terms, this is
    what guarantees the re-run search always returns at least one result.
    """
    terms: list[str] = []
    for key in sorted(chosen):
        term = f"{FACET_KEY}/{key}:{chosen[key]}"
        if " " in term:
            term = f'"{term}"'
        terms.append(term)
    return terms


def build_facets_annotation(chosen: Mapping[str, str]) -> str:
    """``{"emotion": "happy", "pose": "standing"}`` -> ``[facets: emotion=happy pose=standing]: #``."""
    parts: list[str] = []
    for key in sorted(chosen):
        value = chosen[key]
        if " " in value:
            parts.append(f'{key}="{value}"')
        else:
            parts.append(f"{key}={value}")
    return f"[facets: {' '.join(parts)}]: #"


_FACETS_LINE_RE = re.compile(r"^\s*\[facets:\s*(?P<body>.*?)\s*\]:\s*#\s*$")
_FACET_PAIR_RE = re.compile(
    r'(?P<key>[a-zA-Z0-9_.-]+)=(?:"(?P<qval>[^"]*)"|(?P<val>\S+))'
)


def parse_facets_annotation(line: str) -> dict[str, str] | None:
    """Parse one ``[facets: k=v k2="v 2"]: #`` line, or ``None`` if *line* isn't one."""
    m = _FACETS_LINE_RE.match(line)
    if m is None:
        return None
    body = m.group("body")
    result: dict[str, str] = {}
    for pair in _FACET_PAIR_RE.finditer(body):
        value = pair.group("qval")
        if value is None:
            value = pair.group("val")
        result[pair.group("key")] = value
    return result


def find_last_facets(text: str) -> dict[str, str]:
    """Backwards line scan for the most recent ``[facets: ...]: #`` annotation.

    The annotation is stripped from LLM context, so this is how the hysteresis
    input (the previously chosen facet values) is read back off disk.
    """
    for line in reversed(text.split("\n")):
        parsed = parse_facets_annotation(line)
        if parsed is not None:
            return parsed
    return {}
