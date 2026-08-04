"""Tests for facet vocabulary discovery and the ``[facets: ...]`` annotation.

``MediaService.facet_vocabulary`` uses ``LocalMountBackend`` with temp
directories, mirroring ``test_media_service.py``.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

from lens.core.exceptions import MediaSearchCapacityExceeded
from lens.core.media import MediaCache, MediaService
from lens.core.media.facets import (
    build_facets_annotation,
    facet_query_terms,
    find_last_facets,
    parse_facets_annotation,
)
from lens.core.mount import LocalMountBackend


def _make_service(*, search_index_limit: int = 100_000) -> MediaService:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_facets_"))
    backend = LocalMountBackend(tmp)
    cache = MediaCache(search_index_limit=search_index_limit)
    return MediaService(backend, cache=cache)


def _touch(svc: MediaService, rel: str, extra: dict[str, object] | None = None) -> None:
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    svc.put_file(dir_part, name, io.BytesIO(b"hello"))
    if extra:
        svc.update_metadata(rel, extra)


# ---------------------------------------------------------------------------
# facet_vocabulary
# ---------------------------------------------------------------------------


class TestFacetVocabulary:
    def test_multi_value_rule_separates_undecided_from_pinned(self) -> None:
        svc = _make_service()
        _touch(svc, "amy_home_1.jpg", {"facets": {"emotion": "happy", "location": "home"}})
        _touch(svc, "amy_home_2.jpg", {"facets": {"emotion": "sad", "location": "home"}})

        vocab = svc.facet_vocabulary("amy!")
        assert vocab.match_count == 2
        # location has one distinct value across matches -> pinned, not undecided.
        assert vocab.values["location"] == frozenset({"home"})
        assert "location" not in vocab.undecided
        # emotion has two distinct values -> undecided.
        assert vocab.values["emotion"] == frozenset({"happy", "sad"})
        assert vocab.undecided == {"emotion": frozenset({"happy", "sad"})}

    def test_scalar_facet_value(self) -> None:
        svc = _make_service()
        _touch(svc, "amy.jpg", {"facets": {"pose": "standing"}})
        vocab = svc.facet_vocabulary("amy!")
        assert vocab.values["pose"] == frozenset({"standing"})

    def test_list_facet_value(self) -> None:
        svc = _make_service()
        _touch(svc, "amy.jpg", {"facets": {"pose": ["standing", "sitting"]}})
        vocab = svc.facet_vocabulary("amy!")
        assert vocab.values["pose"] == frozenset({"standing", "sitting"})
        assert "pose" in vocab.undecided

    def test_nested_sidecar_only_reads_facets_key(self) -> None:
        svc = _make_service()
        _touch(
            svc,
            "amy.jpg",
            {"facets": {"emotion": "happy"}, "composite": "foreground", "character": "amy"},
        )
        vocab = svc.facet_vocabulary("amy!")
        assert set(vocab.values.keys()) == {"emotion"}

    def test_zero_matches_returns_empty_vocabulary(self) -> None:
        svc = _make_service()
        _touch(svc, "amy.jpg", {"facets": {"emotion": "happy"}})
        vocab = svc.facet_vocabulary("nobody!")
        assert vocab.match_count == 0
        assert vocab.values == {}
        assert vocab.undecided == {}

    def test_capacity_guard_raises(self) -> None:
        svc = _make_service(search_index_limit=1)
        _touch(svc, "a.jpg", {"facets": {"emotion": "happy"}})
        _touch(svc, "b.jpg", {"facets": {"emotion": "sad"}})
        with pytest.raises(MediaSearchCapacityExceeded):
            svc.facet_vocabulary("a!")

    def test_facet_missing_or_wrong_shape_is_ignored(self) -> None:
        svc = _make_service()
        _touch(svc, "a.jpg")  # no facets key at all
        _touch(svc, "b.jpg", {"facets": "not-a-dict"})
        vocab = svc.facet_vocabulary("a! b!")
        assert vocab.values == {}


# ---------------------------------------------------------------------------
# annotation build / parse round-trip
# ---------------------------------------------------------------------------


class TestFacetsAnnotation:
    def test_round_trip_simple_values(self) -> None:
        chosen = {"emotion": "happy", "pose": "standing"}
        line = build_facets_annotation(chosen)
        assert line == "[facets: emotion=happy pose=standing]: #"
        assert parse_facets_annotation(line) == chosen

    def test_round_trip_quoted_value_with_space(self) -> None:
        chosen = {"pose": "arms crossed"}
        line = build_facets_annotation(chosen)
        assert line == '[facets: pose="arms crossed"]: #'
        assert parse_facets_annotation(line) == chosen

    def test_not_a_facets_line_returns_none(self) -> None:
        assert parse_facets_annotation("just some prose") is None
        assert parse_facets_annotation("[write:abc123]: #") is None

    def test_does_not_parse_as_a_lens_operator_annotation(self) -> None:
        from lens.core.annotations import parse_annotations, strip_markdown_comments

        line = build_facets_annotation({"emotion": "happy"})
        text = f"# scene\n\n{line}\n\nSome prose.\n"
        assert parse_annotations(text) == []
        assert line not in strip_markdown_comments(text)


class TestFindLastFacets:
    def test_no_annotation_returns_empty(self) -> None:
        assert find_last_facets("just prose\nmore prose\n") == {}

    def test_finds_the_most_recent_annotation(self) -> None:
        text = (
            "[facets: emotion=sad]: #\n\n"
            "Some prose in between.\n\n"
            "[facets: emotion=happy pose=standing]: #\n\n"
            "More prose.\n"
        )
        assert find_last_facets(text) == {"emotion": "happy", "pose": "standing"}


class TestFacetQueryTerms:
    def test_builds_unrequired_compound_terms(self) -> None:
        terms = facet_query_terms({"emotion": "happy", "pose": "standing"})
        assert terms == ["facets/emotion:happy", "facets/pose:standing"]
        assert all("!" not in t for t in terms)

    def test_quotes_terms_containing_spaces(self) -> None:
        terms = facet_query_terms({"pose": "arms crossed"})
        assert terms == ['"facets/pose:arms crossed"']

    def test_terms_are_directly_usable_as_search_queries(self) -> None:
        svc = _make_service()
        _touch(svc, "amy_happy.jpg", {"facets": {"emotion": "happy"}})
        _touch(svc, "amy_sad.jpg", {"facets": {"emotion": "sad"}})

        terms = facet_query_terms({"emotion": "happy"})
        page = svc.search("amy! " + " ".join(terms))
        assert page.items[0].relative_path == "amy_happy.jpg"
