"""Tests for media search: query parsing, phrase scoring, and MediaService integration."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lens.core.exceptions import MediaSearchCapacityExceeded
from lens.core.media import MediaCache, MediaService
from lens.core.media.search import (
    COMPOUND_WEIGHT,
    KEY_WEIGHT,
    MAX_SCORING_UNITS,
    VALUE_WEIGHT,
    SearchQuery,
    build_search_record,
    compile_query,
    parse_query,
    score_record,
)
from lens.core.mount import LocalMountBackend


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_service(maxsize: int = 100, search_index_limit: int = 10_000) -> tuple[MediaService, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_search_"))
    backend = LocalMountBackend(tmp)
    cache = MediaCache(maxsize=maxsize, search_index_limit=search_index_limit)
    svc = MediaService(backend, cache=cache)
    return svc, tmp


def _touch(svc: MediaService, rel: str) -> None:
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    svc.put_file(dir_part, name, io.BytesIO(b"hello"))


def _score(flattened: dict[str, Any], query_str: str) -> float | None:
    """Score *flattened* against a raw query string, end to end."""
    return score_record(build_search_record(flattened), compile_query(parse_query(query_str)))


def _haystack(flattened: dict[str, Any]) -> str:
    return build_search_record(flattened).haystack


#: A file with a path, reserved fields, a nested field, and free prose.
_FOX: dict[str, Any] = {
    "relative_path": "amy/house/office.jpg",
    "name": "office.jpg",
    "extension": ".jpg",
    "type": "image",
    "prompt": "a quick brown fox jumps over the lazy dog",
    "composite": {"type": "subject"},
}


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_empty_string(self) -> None:
        assert parse_query("") == SearchQuery()

    def test_scoring_terms(self) -> None:
        q = parse_query("couch bed sitting")
        assert q.scoring_terms == ("couch", "bed", "sitting")
        assert q.required_terms == ()

    def test_required_terms(self) -> None:
        q = parse_query("amy! house!")
        assert q.required_terms == ("amy", "house")
        assert q.scoring_terms == ()

    def test_kv_is_a_scoring_term_not_a_filter(self) -> None:
        """The old hard-filter meaning of `key:value` now needs an explicit `!`."""
        assert parse_query("type:image").scoring_terms == ("type:image",)
        assert parse_query("type:image!").required_terms == ("type:image",)

    def test_nested_kv_stays_one_term(self) -> None:
        assert parse_query("composite/type:subject").scoring_terms == ("composite/type:subject",)

    def test_quoted_phrase_is_one_unit(self) -> None:
        q = parse_query('"quick brown fox" jumps')
        assert q.scoring_terms == ("quick brown fox", "jumps")

    def test_required_quoted_phrase(self) -> None:
        q = parse_query('"brown hair"! amy')
        assert q.required_terms == ("brown hair",)
        assert q.scoring_terms == ("amy",)

    def test_quoted_phrase_whitespace_collapsed(self) -> None:
        assert parse_query('"  brown   hair  "').scoring_terms == ("brown hair",)

    def test_unterminated_quote_runs_to_end(self) -> None:
        assert parse_query('amy "brown hair').scoring_terms == ("amy", "brown hair")

    def test_empty_quotes_dropped(self) -> None:
        assert parse_query('amy ""').scoring_terms == ("amy",)

    def test_lone_bang_is_not_a_term(self) -> None:
        """`!` alone leaves an empty query — which matches everything."""
        assert parse_query("!") == SearchQuery()

    def test_lowercased(self) -> None:
        q = parse_query('AMY! "Brown Hair" Type:Image')
        assert q.required_terms == ("amy",)
        assert q.scoring_terms == ("brown hair", "type:image")

    def test_quote_mid_token_is_literal(self) -> None:
        assert parse_query('a"b').scoring_terms == ('a"b',)

    def test_mixed_query(self) -> None:
        q = parse_query('amy! "brown hair"! type:image composite/type:subject couch bed')
        assert q.required_terms == ("amy", "brown hair")
        assert q.scoring_terms == ("type:image", "composite/type:subject", "couch", "bed")


# ---------------------------------------------------------------------------
# build_search_record — the denormalized haystack
# ---------------------------------------------------------------------------


class TestBuildSearchRecord:
    def test_key_value_denormalized_into_haystack(self) -> None:
        assert "type:image" in _haystack({"type": "image"})

    def test_nested_keys_joined_with_slash(self) -> None:
        assert "composite/type:subject" in _haystack({"composite": {"type": "subject"}})

    def test_deeply_nested_keys(self) -> None:
        assert "a/b/c:value" in _haystack({"a": {"b": {"c": "value"}}})

    def test_sequence_values_emit_one_chunk_each(self) -> None:
        hay = _haystack({"tags": ["cute", "fox"]})
        assert "tags:cute" in hay
        assert "tags:fox" in hay

    def test_empty_value_still_records_the_key(self) -> None:
        assert "notes:" in _haystack({"notes": None})

    def test_fields_separated_by_the_sentinel_not_a_space(self) -> None:
        """Otherwise a phrase could match across the seam of two fields."""
        hay = _haystack({"color": "brown", "hair": "long"})
        assert "color:brown\x1fhair:long" in hay

    def test_value_colons_and_slashes_sanitized(self) -> None:
        """A timestamp or a stray "style: anime" must not fake KV structure."""
        hay = _haystack({"prompt": "shot at 12:34:56 in style: anime"})
        assert "12 34 56" in hay
        assert "style:anime" not in hay

    def test_path_fields_keep_their_slashes(self) -> None:
        assert "relative_path:amy/house/office.jpg" in _haystack(
            {"relative_path": "amy/house/office.jpg"}
        )

    def test_haystack_is_space_padded(self) -> None:
        hay = _haystack({"type": "image"})
        assert hay.startswith(" ") and hay.endswith(" ")

    def test_non_string_values_stringified(self) -> None:
        hay = _haystack({"width": 512, "keep": True})
        assert "width:512" in hay
        assert "keep:true" in hay

    def test_tokens_are_the_delimited_words(self) -> None:
        record = build_search_record({"path": "amy/house/office.jpg"})
        assert {"path", "amy", "house", "office", "jpg"} == record.tokens

    def test_filename_word_separators_split_tokens(self) -> None:
        """Real filenames separate words with `-` and `_`, not spaces."""
        record = build_search_record({"name": "sitting-facing_rogue.jpg"})
        assert {"name", "sitting", "facing", "rogue", "jpg"} == record.tokens

    def test_flattened_is_retained_for_renames(self) -> None:
        flattened = {"relative_path": "a.jpg", "type": "image"}
        assert build_search_record(flattened).flattened == flattened


# ---------------------------------------------------------------------------
# score_record — required terms
# ---------------------------------------------------------------------------


class TestRequiredTerms:
    def test_required_term_in_path(self) -> None:
        assert _score(_FOX, "amy!") == 0.0

    def test_required_term_missing(self) -> None:
        assert _score(_FOX, "zebra!") is None

    def test_required_terms_are_anded(self) -> None:
        assert _score(_FOX, "amy! office!") == 0.0
        assert _score(_FOX, "amy! zebra!") is None

    def test_required_term_does_not_score(self) -> None:
        assert _score(_FOX, "amy! house! office!") == 0.0

    def test_required_compound_acts_as_a_hard_filter(self) -> None:
        assert _score(_FOX, "type:image!") == 0.0
        assert _score(_FOX, "type:video!") is None

    def test_required_term_is_case_insensitive(self) -> None:
        assert _score(_FOX, "AMY!") == 0.0

    def test_required_phrase_must_be_contiguous(self) -> None:
        assert _score(_FOX, '"brown fox"!') == 0.0
        assert _score(_FOX, '"fox brown"!') is None
        assert _score(_FOX, '"quick fox"!') is None

    def test_required_phrase_cannot_span_two_fields(self) -> None:
        """The sentinel between fields is what prevents this."""
        crossing = {"color": "brown", "hair": "long"}
        assert _score(crossing, '"brown hair"!') is None
        assert _score(crossing, "brown! hair!") == 0.0

    def test_required_term_matches_whole_words_only(self) -> None:
        assert _score(_FOX, "fo!") is None
        assert _score(_FOX, "foxes!") is None

    def test_required_filter_survives_scoring_terms(self) -> None:
        assert _score(_FOX, "zebra! quick") is None


# ---------------------------------------------------------------------------
# score_record — class weights
# ---------------------------------------------------------------------------


class TestClassWeights:
    def test_bare_key_scores_key_class(self) -> None:
        assert _score({"character": "amy"}, "character") == KEY_WEIGHT

    def test_bare_value_scores_value_class(self) -> None:
        assert _score({"character": "amy"}, "amy") == VALUE_WEIGHT

    def test_compound_outranks_both(self) -> None:
        assert _score({"character": "amy"}, "character:amy") == COMPOUND_WEIGHT

    def test_nested_compound(self) -> None:
        """Two words (`composite`, `type:subject`) at the compound weight."""
        flat = {"composite": {"type": "subject"}}
        assert _score(flat, "composite/type:subject") == COMPOUND_WEIGHT * 4

    def test_free_text_interior_scores_plain(self) -> None:
        assert _score({"prompt": "a quick brown fox"}, "brown") == VALUE_WEIGHT

    def test_strongest_class_wins_across_occurrences(self) -> None:
        """`type` is a key here and a value there — the key class doesn't win."""
        flat = {"type": "image", "kind": "type"}
        assert _score(flat, "type") == VALUE_WEIGHT

    def test_wrong_compound_does_not_match(self) -> None:
        assert _score({"character": "amy"}, "character:bob") is None


# ---------------------------------------------------------------------------
# score_record — contiguous runs and non-overlapping selection
# ---------------------------------------------------------------------------


class TestRunScoring:
    def test_single_word_run(self) -> None:
        assert _score(_FOX, "quick") == VALUE_WEIGHT

    def test_contiguous_phrase_beats_scattered_words(self) -> None:
        contiguous = _score(_FOX, "quick brown fox")
        scattered = _score(_FOX, "quick lazy")
        assert contiguous is not None and scattered is not None
        assert contiguous > scattered

    def test_run_weight_is_quadratic_in_length(self) -> None:
        assert _score(_FOX, "quick brown") == VALUE_WEIGHT * 4
        assert _score(_FOX, "quick brown fox") == VALUE_WEIGHT * 9

    def test_phrase_is_not_summed_with_its_own_sub_runs(self) -> None:
        """Naive summing would score this as 1+1+1+4+4+9; the DP picks 9."""
        assert _score(_FOX, "quick brown fox") == VALUE_WEIGHT * 9

    def test_non_overlapping_runs_combine(self) -> None:
        # "quick brown fox" (9) + "dog" (1) — "fox dog" isn't contiguous.
        assert _score(_FOX, "quick brown fox dog") == VALUE_WEIGHT * 10

    def test_word_order_matters(self) -> None:
        assert _score(_FOX, "brown fox") == VALUE_WEIGHT * 4
        assert _score(_FOX, "fox brown") == VALUE_WEIGHT * 2

    def test_path_segments_match_as_an_ordered_run(self) -> None:
        assert _score(_FOX, "amy house office") == VALUE_WEIGHT * 9

    def test_filename_word_separators_match_as_an_ordered_run(self) -> None:
        flat = {"name": "sitting-facing_rogue.jpg"}
        assert _score(flat, "sitting facing") == VALUE_WEIGHT * 4
        assert _score(flat, "facing sitting") == VALUE_WEIGHT * 2

    def test_separators_are_interchangeable_between_query_and_file(self) -> None:
        """`sitting-facing` and `sitting facing` are the same query."""
        flat = {"name": "sitting-facing.jpg"}
        spaced = _score(flat, "sitting facing")
        assert spaced == VALUE_WEIGHT * 4
        assert _score(flat, "sitting-facing") == spaced
        assert _score(flat, "sitting_facing") == spaced
        assert _score({"name": "sitting facing.jpg"}, "sitting-facing") == spaced

    def test_pasting_back_a_relative_path_scores_as_one_long_run(self) -> None:
        assert _score(_FOX, "amy/house/office.jpg") == VALUE_WEIGHT * 16

    def test_quoted_phrase_scores_like_the_same_words_unquoted(self) -> None:
        assert _score(_FOX, '"quick brown fox"') == _score(_FOX, "quick brown fox")

    def test_quoted_phrase_is_never_split(self) -> None:
        """`"fox brown"` can't be rearranged into the contiguous `brown fox`."""
        assert _score(_FOX, '"fox brown"') is None

    def test_quoted_phrase_combines_with_neighbours(self) -> None:
        assert _score(_FOX, '"quick brown" fox') == VALUE_WEIGHT * 9

    def test_repeated_match_counts_once(self) -> None:
        """Set semantics: a rambling prompt must not outrank exact metadata."""
        repeated = _score({"prompt": "fox fox fox fox"}, "fox")
        once = _score({"prompt": "fox"}, "fox")
        assert repeated == once

    def test_compound_run_beats_its_parts(self) -> None:
        flat = {"character": "amy"}
        compound = _score(flat, "character:amy")
        parts = _score(flat, "character amy")
        assert compound is not None and parts is not None
        assert compound > parts


# ---------------------------------------------------------------------------
# score_record — disqualification, normalization, limits
# ---------------------------------------------------------------------------


class TestScoreRecordSemantics:
    def test_empty_query_matches_everything_at_zero(self) -> None:
        assert _score(_FOX, "") == 0.0

    def test_no_scoring_term_matches_disqualifies(self) -> None:
        assert _score(_FOX, "zebra") is None

    def test_partial_scoring_match_is_kept(self) -> None:
        assert _score(_FOX, "quick zebra") == VALUE_WEIGHT

    def test_whole_word_matching_only(self) -> None:
        assert _score(_FOX, "qui") is None
        assert _score(_FOX, "uick") is None

    def test_extension_is_matchable(self) -> None:
        assert _score(_FOX, "jpg") == VALUE_WEIGHT

    def test_numbers_match_as_typed(self) -> None:
        assert _score({"width": 512}, "width:512") == COMPOUND_WEIGHT

    def test_booleans_match_as_lowercase_words(self) -> None:
        assert _score({"keep": True}, "keep:true") == COMPOUND_WEIGHT

    def test_scoring_units_are_capped(self) -> None:
        query = compile_query(SearchQuery(scoring_terms=tuple(f"w{i}" for i in range(50))))
        assert len(query.units) == MAX_SCORING_UNITS

    def test_query_object_terms_normalized_at_compile_time(self) -> None:
        """Hand-built SearchQuery objects get the same lowercasing as parsing."""
        record = build_search_record({"character": "amy"})
        query = compile_query(SearchQuery(scoring_terms=("  AMY  ",)))
        assert score_record(record, query) == VALUE_WEIGHT


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

    def test_search_required_term_matches_filename_stem(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")
        assert len(svc.search("couch!").items) == 1

    def test_search_compound_ranks_by_type(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "photo.jpg")
        _touch(svc, "video.mp4")
        page = svc.search("type:image")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "photo.jpg"

    def test_search_scoring_terms_ranked(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")  # matches "couch"
        _touch(svc, "amy/house/bed.jpg")  # matches "bed"
        _touch(svc, "bob/apt/table.jpg")  # fails the required term
        page = svc.search("amy! couch bed")
        assert len(page.items) == 2
        assert {r.relative_path for r in page.items} == {
            "amy/house/bed.jpg",
            "amy/house/couch.jpg",
        }
        assert all(r.score == VALUE_WEIGHT for r in page.items)

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

    def test_search_kv_ranks_rather_than_filters(self) -> None:
        """Both files match; the one satisfying both terms ranks first."""
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob", "expression": "happy"})
        page = svc.search("expression:happy character:amy")
        assert [r.relative_path for r in page.items] == ["amy.jpg", "bob.jpg"]
        assert page.items[0].score > page.items[1].score

    def test_search_kv_filters_when_required(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.update_metadata("amy.jpg", {"character": "amy", "expression": "happy"})
        _touch(svc, "bob.jpg")
        svc.update_metadata("bob.jpg", {"character": "bob", "expression": "happy"})
        page = svc.search("expression:happy! character:amy!")
        assert [r.relative_path for r in page.items] == ["amy.jpg"]

    def test_search_returns_sorted_by_score_then_path(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "z/both.jpg")
        _touch(svc, "a/both.jpg")
        _touch(svc, "m/no.jpg")
        page = svc.search("both!")
        assert len(page.items) == 2
        assert page.items[0].relative_path == "a/both.jpg"
        assert page.items[1].relative_path == "z/both.jpg"

    def test_search_never_touches_backend_after_warm(self) -> None:
        """Once warmed, search scans only the precomputed search index —
        it never calls into MediaCache's LRU (list:/meta:), let alone the
        backend, so hits/misses on that cache stay flat across searches."""
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.search("amy!")  # triggers warm
        stats_before = svc.cache.stats()
        page = svc.search("amy!")
        assert len(page.items) == 1
        assert svc.cache.stats()["hits"] == stats_before["hits"]
        assert svc.cache.stats()["misses"] == stats_before["misses"]

    def test_adjacent_path_segments_outrank_scattered_matches(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy/house/couch.jpg")  # "house couch" is one run
        _touch(svc, "amy/couch/attic/house.jpg")  # same words, not adjacent
        page = svc.search("amy! house couch")
        assert len(page.items) == 2
        assert page.items[0].relative_path == "amy/house/couch.jpg"
        assert page.items[0].score > page.items[1].score

    def test_search_quoted_phrase_in_metadata(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a.jpg")
        svc.update_metadata("a.jpg", {"prompt": "a girl with brown hair"})
        _touch(svc, "b.jpg")
        svc.update_metadata("b.jpg", {"hair": "long", "color": "brown"})
        page = svc.search('"brown hair"!')
        assert [r.relative_path for r in page.items] == ["a.jpg"]

    def test_deeply_nested_directory_structure(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "a/b/c/d/e/deep.jpg")
        page = svc.search("deep!")
        assert len(page.items) == 1
        assert page.items[0].relative_path == "a/b/c/d/e/deep.jpg"


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

    def test_search_reflects_delete(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        page = svc.search("amy!")
        assert len(page.items) == 1
        svc.delete("amy.jpg")
        page2 = svc.search("amy!")
        assert page2.items == ()

    def test_search_reflects_move(self) -> None:
        svc, _ = _make_service()
        _touch(svc, "amy.jpg")
        svc.move("amy.jpg", "bob.jpg")
        assert svc.search("amy!").items == ()
        assert len(svc.search("bob!").items) == 1


# ---------------------------------------------------------------------------
# Search index capacity: locked-empty semantics
# ---------------------------------------------------------------------------


class TestSearchCapacity:
    def test_search_raises_when_file_count_exceeds_limit(self) -> None:
        svc, _ = _make_service(search_index_limit=2)
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        _touch(svc, "c.jpg")
        with pytest.raises(MediaSearchCapacityExceeded):
            svc.search("a!")

    def test_search_works_at_exactly_the_limit(self) -> None:
        svc, _ = _make_service(search_index_limit=2)
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        page = svc.search("a.jpg!")
        assert len(page.items) == 1

    def test_over_capacity_index_stays_locked_after_a_delete(self) -> None:
        """Dropping back under the limit doesn't silently recover — that's
        an explicit config/invalidate decision, not automatic."""
        svc, _ = _make_service(search_index_limit=2)
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        _touch(svc, "c.jpg")
        with pytest.raises(MediaSearchCapacityExceeded):
            svc.search("a!")
        svc.delete("c.jpg")
        with pytest.raises(MediaSearchCapacityExceeded):
            svc.search("a!")

    def test_recovers_once_reconstructed_with_a_higher_limit(self) -> None:
        """The realistic recovery path: [project] media_search_index_limit
        is raised in lens.toml and the process picks up a fresh MediaCache
        (new server process, or a new project_slug cache entry) — modeled
        here by pointing a new MediaService at the same backend."""
        svc, tmp = _make_service(search_index_limit=2)
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        _touch(svc, "c.jpg")
        with pytest.raises(MediaSearchCapacityExceeded):
            svc.search("a!")

        backend = LocalMountBackend(tmp)
        svc2 = MediaService(backend, cache=MediaCache(search_index_limit=10))
        page = svc2.search("!")  # empty query — every indexed file
        assert len(page.items) == 3

    def test_capacity_error_message_names_the_limit(self) -> None:
        svc, _ = _make_service(search_index_limit=1)
        _touch(svc, "a.jpg")
        _touch(svc, "b.jpg")
        with pytest.raises(MediaSearchCapacityExceeded) as exc_info:
            svc.search("a!")
        assert "1" in str(exc_info.value)
        assert "media_search_index_limit" in str(exc_info.value)
