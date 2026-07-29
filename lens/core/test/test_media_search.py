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
        result = svc.search("")
        assert result.items == ()
        assert result.total_items == 0
        assert result.total_pages == 1
        assert result.current_page == 1

    def test_search_no_match(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        result = svc.search("bob!")
        assert result.items == ()
        assert result.total_items == 0

    def test_search_required_term_matches_path(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")
        page = svc.search("amy!")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "amy/house/couch.jpg"

    def test_search_kv_match_type(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "photo.jpg")
        _touch(svc, "video.mp4")
        page = svc.search("type:image")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "photo.jpg"

    def test_search_optional_terms_ranked(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")  # matches "couch"
        _touch(svc, "amy/house/bed.jpg")  # matches "bed"
        _touch(svc, "bob/apt/table.jpg")  # matches nothing
        page = svc.search("amy! couch bed")
        assert len(page.items) == 2
        assert page.items[0].score == 1
        assert page.items[1].score == 1
        assert {r.relative_path for r in page.items} == {
            "amy/house/bed.jpg",
            "amy/house/couch.jpg",
        }

    def test_search_with_sidecar_extra(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob"})
        page = svc.search("character:amy")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "amy.jpg"

    def test_search_nested_kv(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "subject.png")
        svc.update_metadata("subject.png", {"composite": {"type": "subject"}})
        _touch(svc, "bg.png")
        svc.update_metadata("bg.png", {"composite": {"type": "background"}})
        page = svc.search("composite/type:subject")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "subject.png"

    def test_search_mixed_query(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "chars/amy/portrait.jpg")
        svc.update_metadata("chars/amy/portrait.jpg", {"character": "amy", "style": "portrait"})
        _touch(svc, "chars/bob/portrait.jpg")
        svc.update_metadata("chars/bob/portrait.jpg", {"character": "bob", "style": "portrait"})
        _touch(svc, "chars/amy/fullbody.jpg")
        svc.update_metadata("chars/amy/fullbody.jpg", {"character": "amy", "style": "fullbody"})
        page = svc.search("amy! style:portrait")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "chars/amy/portrait.jpg"

    def test_search_returns_sorted_by_score_then_path(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "z/both.jpg")
        _touch(svc, "a/both.jpg")
        _touch(svc, "m/no.jpg")
        page = svc.search("both!")
        assert len(page.items) == 2
        assert page.items[0].relative_path == "a/both.jpg"
        assert page.items[1].relative_path == "z/both.jpg"

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
        page = svc.search("amy! house couch bed")
        # amy/house/couch.jpg: score=2 (house, couch)
        # amy/house/table.jpg: score=1 (house)
        assert len(page.items) == 2
        assert page.items[0].score == 2
        assert page.items[0].relative_path == "amy/house/couch.jpg"
        assert page.items[1].score == 1
        assert page.items[1].relative_path == "amy/house/table.jpg"

    def test_deeply_nested_directory_structure(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a/b/c/d/e/deep.jpg")
        page = svc.search("deep!")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "a/b/c/d/e/deep.jpg"

    def test_search_multiple_kv_pairs(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob", "expression": "happy"})
        page = svc.search("expression:happy character:amy")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "amy.jpg"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestSearchPagination:
    def test_default_page_is_first(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        _touch(svc, "c.jpg")
        page = svc.search("!")
        assert page.current_page == 1
        assert len(page.items) == 3
        assert page.total_pages == 1
        assert page.total_items == 3

    def test_page_size_is_20(self) -> None:
        svc, _ = _make_service()
        for i in range(25):
            _touch(svc, f"img_{i:02d}.jpg")
        page1 = svc.search("!")
        assert len(page1.items) == 20
        assert page1.total_pages == 2
        assert page1.total_items == 25
        assert page1.current_page == 1

    def test_second_page(self) -> None:
        svc, _ = _make_service()
        for i in range(25):
            _touch(svc, f"img_{i:02d}.jpg")
        page2 = svc.search("!", page=2)
        assert len(page2.items) == 5
        assert page2.current_page == 2
        assert page2.total_pages == 2
        assert page2.total_items == 25

    def test_page_too_high_clamps_to_last_page(self) -> None:
        svc, _ = _make_service()
        for i in range(5):
            _touch(svc, f"img_{i:02d}.jpg")
        page = svc.search("!", page=10)
        assert len(page.items) == 5
        assert page.current_page == 1
        assert page.total_pages == 1

    def test_page_below_one_is_clamped(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a.jpg")
        page = svc.search("!", page=0)
        assert page.current_page == 1
        assert len(page.items) == 1

    def test_page_keeps_items_in_correct_order(self) -> None:
        svc, _ = _make_service()
        for i in range(22):
            _touch(svc, f"img_{i:02d}.jpg")
        page1 = svc.search("!")
        page2 = svc.search("!", page=2)
        assert len(page1.items) == 20
        assert len(page2.items) == 2
        assert page1.items[0].relative_path < page1.items[-1].relative_path

    def test_exact_page_boundary(self) -> None:
        svc, _ = _make_service()
        for i in range(20):
            _touch(svc, f"img_{i:02d}.jpg")
        page = svc.search("!")
        assert len(page.items) == 20
        assert page.total_pages == 1
        assert page.total_items == 20

    def test_page_size_constant(self) -> None:
        svc, _ = _make_service()
        for i in range(40):
            _touch(svc, f"img_{i:02d}.jpg")
        page = svc.search("!")
        assert page.page_size == 20
        assert page.total_pages == 2

    def test_single_result_pagination(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "only.jpg")
        page = svc.search("only!")
        assert len(page.items) == 1
        assert page.total_items == 1
        assert page.total_pages == 1
        assert page.current_page == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSearchEdgeCases:
    def test_no_files_on_mount(self) -> None:
        svc, _ = _make_service()
        result = svc.search("anything")
        assert result.items == ()
        assert result.total_items == 0

    def test_only_directories_no_files(self) -> None:
        svc, _ = _make_service()
        # Create an empty directory
        svc._backend.put_file("subdir", ".gitkeep", io.BytesIO(b""))  # pyright: ignore[reportPrivateUsage]
        svc.delete("subdir/.gitkeep")
        result = svc.search("anything")
        assert result.items == ()

    def test_hidden_files_skipped(self) -> None:
        svc, _ = _make_service()
        _touch(svc, ".hidden.jpg")
        assert svc.search("hidden!").items == ()

    def test_unsupported_extension_skipped(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "data.bin")
        assert svc.search("data!").items == ()

    def test_search_cursor_does_not_raise(self) -> None:
        """Missing or deleted files during walk should be skipped."""
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        page = svc.search("amy!")
        assert len(page.items) == 1
        # If a file is deleted between walk and metadata fetch, we skip
        svc.delete("amy.jpg")
        page2 = svc.search("amy!")
        assert page2.items == ()
