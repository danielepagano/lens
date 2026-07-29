"""Tests for media search: query parsing, matching, and integration with MediaService."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from lens.core.media import MediaCache, MediaService
from lens.core.media.search import (
    SearchQuery,
    parse_query,
    score_query,
)
from lens.core.mount import LocalMountBackend


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_service(maxsize: int = 100) -> tuple[MediaService, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_search_"))
    backend = LocalMountBackend(tmp)
    cache = MediaCache(maxsize=maxsize)
    svc = MediaService(backend, cache=cache)
    return svc, tmp


def _touch(svc: MediaService, rel: str) -> None:
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    svc.put_file(dir_part, name, io.BytesIO(b"hello"))


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_empty_string(self) -> None:
        q = parse_query("")
        assert q == SearchQuery()

    def test_required_terms(self) -> None:
        q = parse_query("amy! house!")
        assert q.required_terms == ("amy", "house")

    def test_kv_pairs(self) -> None:
        q = parse_query("type:image")
        assert q.kv_pairs == (("type", "image"),)

    def test_nested_kv_pairs(self) -> None:
        q = parse_query("composite/type:subject")
        assert q.nested_kv_pairs == (("composite", "type", "subject"),)

    def test_deeply_nested_kv(self) -> None:
        q = parse_query("a/b/c:value")
        assert q.nested_kv_pairs == (("a/b", "c", "value"),)

    def test_optional_terms(self) -> None:
        q = parse_query("couch bed sitting")
        assert q.optional_terms == ("couch", "bed", "sitting")

    def test_mixed_query(self) -> None:
        q = parse_query("amy! house! type:image composite/type:subject couch bed")
        assert q.required_terms == ("amy", "house")
        assert q.kv_pairs == (("type", "image"),)
        assert q.nested_kv_pairs == (("composite", "type", "subject"),)
        assert q.optional_terms == ("couch", "bed")

    def test_kv_value_contains_colon(self) -> None:
        q = parse_query("key:val:ue")
        # partition gives ("key", ":", "val:ue")
        assert q.kv_pairs == (("key", "val:ue"),)

    def test_required_with_colon_not_confused(self) -> None:
        q = parse_query("amy!:type")
        # "amy!:type" contains ':' so it's a KV pair, not a required term
        assert q.required_terms == ()
        assert q.kv_pairs == (("amy!", "type"),)

    def test_trailing_exclamation_kv(self) -> None:
        q = parse_query("key!:value")
        assert q.kv_pairs == (("key!", "value"),)


# ---------------------------------------------------------------------------
# score_query (matching logic)
# ---------------------------------------------------------------------------


class TestScoreQuery:
    def test_empty_query_matches_anything(self) -> None:
        q = SearchQuery()
        assert score_query({"type": "image"}, {}, q) == 0

    def test_required_term_present_in_relative_path(self) -> None:
        q = SearchQuery(required_terms=("amy",))
        assert score_query({"relative_path": "amy/house.jpg"}, {}, q) == 0

    def test_required_term_missing(self) -> None:
        q = SearchQuery(required_terms=("amy",))
        assert score_query({"relative_path": "bob/house.jpg"}, {}, q) is None

    def test_required_term_in_extra(self) -> None:
        q = SearchQuery(required_terms=("amy",))
        assert score_query({"name": "pic.jpg", "character": "amy"}, {}, q) == 0

    def test_required_term_case_insensitive(self) -> None:
        q = SearchQuery(required_terms=("AMY",))
        assert score_query({"relative_path": "Amy/House.jpg"}, {}, q) == 0

    def test_kv_match_reserved_key(self) -> None:
        q = SearchQuery(kv_pairs=(("type", "image"),))
        assert score_query({"type": "image"}, {}, q) == 0

    def test_kv_mismatch(self) -> None:
        q = SearchQuery(kv_pairs=(("type", "video"),))
        assert score_query({"type": "image"}, {}, q) is None

    def test_kv_match_extra_key(self) -> None:
        q = SearchQuery(kv_pairs=(("character", "amy"),))
        assert score_query({"name": "pic.jpg", "character": "amy"}, {}, q) == 0

    def test_kv_case_insensitive(self) -> None:
        q = SearchQuery(kv_pairs=(("type", "IMAGE"),))
        assert score_query({"type": "image"}, {}, q) == 0

    def test_nested_kv_match(self) -> None:
        q = SearchQuery(nested_kv_pairs=(("composite", "type", "subject"),))
        assert score_query({"name": "pic.jpg"}, {"composite": {"type": "subject"}}, q) == 0

    def test_nested_kv_mismatch(self) -> None:
        q = SearchQuery(nested_kv_pairs=(("composite", "type", "subject"),))
        assert score_query({"name": "pic.jpg"}, {"composite": {"type": "bg"}}, q) is None

    def test_nested_kv_missing_path(self) -> None:
        q = SearchQuery(nested_kv_pairs=(("composite", "type", "subject"),))
        assert score_query({"name": "pic.jpg"}, {}, q) is None

    def test_optional_terms_scored(self) -> None:
        q = SearchQuery(optional_terms=("couch", "bed", "sitting"))
        # "couch" is in path, "bed" is not, "sitting" is not
        assert score_query({"relative_path": "couch/pic.jpg"}, {}, q) == 1

    def test_optional_terms_all_match(self) -> None:
        q = SearchQuery(optional_terms=("amy", "house"))
        assert score_query({"relative_path": "amy/house.jpg", "name": "house.jpg"}, {}, q) == 2

    def test_optional_terms_none_match_returns_none(self) -> None:
        q = SearchQuery(optional_terms=("zebra",))
        assert score_query({"relative_path": "amy/house.jpg"}, {}, q) is None

    def test_no_optional_terms_fine(self) -> None:
        q = SearchQuery(required_terms=("amy",), kv_pairs=(("type", "image"),))
        assert score_query({"relative_path": "amy/pic.jpg", "type": "image"}, {}, q) == 0

    def test_all_checks_combined(self) -> None:
        q = SearchQuery(
            required_terms=("amy",),
            kv_pairs=(("type", "image"),),
            nested_kv_pairs=(("composite", "type", "subject"),),
            optional_terms=("couch", "bed"),
        )
        flattened = {
            "relative_path": "amy/house/couch/pic.jpg",
            "type": "image",
            "character": "amy",
        }
        extra = {"composite": {"type": "subject", "position": "left"}}
        assert score_query(flattened, extra, q) == 1  # "couch" matches

    def test_stringified_number_values_searchable(self) -> None:
        q = SearchQuery(optional_terms=("42",))
        assert score_query({"number": 42}, {}, q) == 1


# ---------------------------------------------------------------------------
# MediaService.search — integration
# ---------------------------------------------------------------------------


class TestMediaServiceSearch:
    def test_search_empty_mount(self) -> None:
        svc, _ = _make_service()
        assert svc.search("") == []

    def test_search_no_match(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        assert svc.search("bob!") == []

    def test_search_required_term_matches_path(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")
        results = svc.search("amy!")
        assert len(results) == 1
        assert results[0].relative_path == "amy/house/couch.jpg"

    def test_search_kv_match_type(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "photo.jpg")
        _touch(svc, "video.mp4")
        results = svc.search("type:image")
        assert len(results) == 1
        assert results[0].relative_path == "photo.jpg"

    def test_search_optional_terms_ranked(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")  # matches "couch"
        _touch(svc, "amy/house/bed.jpg")  # matches "bed"
        _touch(svc, "bob/apt/table.jpg")  # matches nothing
        results = svc.search("amy! couch bed")
        assert len(results) == 2
        # Both match "amy!", but couch.jpg scores 1, bed.jpg scores 0
        # Wait: "bed" is an optional term, so "bed.jpg" would match "bed".
        # Actually: path is "amy/house/bed.jpg", so "bed" is in the relative_path.
        # So both score 1. Then sorted by score desc, then path asc.
        assert results[0].score == 1
        assert results[1].score == 1
        assert {r.relative_path for r in results} == {
            "amy/house/bed.jpg",
            "amy/house/couch.jpg",
        }

    def test_search_with_sidecar_extra(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob"})
        results = svc.search("character:amy")
        assert len(results) == 1
        assert results[0].relative_path == "amy.jpg"

    def test_search_nested_kv(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "subject.png")
        svc.update_metadata("subject.png", {"composite": {"type": "subject"}})
        _touch(svc, "bg.png")
        svc.update_metadata("bg.png", {"composite": {"type": "background"}})
        results = svc.search("composite/type:subject")
        assert len(results) == 1
        assert results[0].relative_path == "subject.png"

    def test_search_mixed_query(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "chars/amy/portrait.jpg")
        svc.update_metadata("chars/amy/portrait.jpg", {"character": "amy", "style": "portrait"})
        _touch(svc, "chars/bob/portrait.jpg")
        svc.update_metadata("chars/bob/portrait.jpg", {"character": "bob", "style": "portrait"})
        _touch(svc, "chars/amy/fullbody.jpg")
        svc.update_metadata("chars/amy/fullbody.jpg", {"character": "amy", "style": "fullbody"})
        results = svc.search("amy! style:portrait")
        assert len(results) == 1
        assert results[0].relative_path == "chars/amy/portrait.jpg"

    def test_search_returns_sorted_by_score_then_path(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "z/both.jpg")
        _touch(svc, "a/both.jpg")
        _touch(svc, "m/no.jpg")
        results = svc.search("both!")
        assert len(results) == 2
        assert results[0].relative_path == "a/both.jpg"
        assert results[1].relative_path == "z/both.jpg"

    def test_search_uses_cached_listings(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.search("amy!")  # primes list + meta cache
        hits_before = svc.cache.hits
        svc.search("amy!")
        assert svc.cache.hits > hits_before

    def test_search_multiple_files_different_scores(self) -> None:
        """Files with more matching optional terms rank higher."""
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")  # matches: amy, house, couch
        _touch(svc, "amy/house/table.jpg")  # matches: amy, house
        results = svc.search("amy! house couch bed")
        # amy/house/couch.jpg: score=2 (house, couch)
        # amy/house/table.jpg: score=1 (house)
        assert len(results) == 2
        assert results[0].score == 2
        assert results[0].relative_path == "amy/house/couch.jpg"
        assert results[1].score == 1
        assert results[1].relative_path == "amy/house/table.jpg"

    def test_deeply_nested_directory_structure(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a/b/c/d/e/deep.jpg")
        results = svc.search("deep!")
        assert len(results) == 1
        assert results[0].relative_path == "a/b/c/d/e/deep.jpg"

    def test_search_multiple_kv_pairs(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob", "expression": "happy"})
        results = svc.search("expression:happy character:amy")
        assert len(results) == 1
        assert results[0].relative_path == "amy.jpg"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSearchEdgeCases:
    def test_no_files_on_mount(self) -> None:
        svc, _ = _make_service()
        assert svc.search("anything") == []

    def test_only_directories_no_files(self) -> None:
        svc, _ = _make_service()
        # Create an empty directory
        svc._backend.put_file("subdir", ".gitkeep", io.BytesIO(b""))  # pyright: ignore[reportPrivateUsage]
        svc.delete("subdir/.gitkeep")
        assert svc.search("anything") == []

    def test_hidden_files_skipped(self) -> None:
        svc, _ = _make_service()
        _touch(svc, ".hidden.jpg")
        assert svc.search("hidden!") == []

    def test_unsupported_extension_skipped(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "data.bin")
        assert svc.search("data!") == []

    def test_search_cursor_does_not_raise(self) -> None:
        """Missing or deleted files during walk should be skipped."""
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        results = svc.search("amy!")
        assert len(results) == 1
        # If a file is deleted between walk and metadata fetch, we skip
        svc.delete("amy.jpg")
        results2 = svc.search("amy!")
        assert results2 == []
