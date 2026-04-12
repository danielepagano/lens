"""Unit tests for lens.core.text_select — line-content-based selections."""

from __future__ import annotations

import unittest

from lens.core.text_select import (
    END_ANCHOR,
    START_ANCHOR,
    LineSelector,
    Patch,
    Selection,
    SelectionError,
    apply_patch,
    apply_patches,
    apply_patches_to_storage_llm_view,
    parse_patches,
    resolve_selection,
    resolve_storage_selection_to_disk_inclusive_lines,
    storage_text_llm_view,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sel(
    target: str,
    before: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
) -> LineSelector:
    return LineSelector(target=target, before=before, after=after)


def _range(start: LineSelector, end: LineSelector | None = None) -> Selection:
    return Selection(start=start, end=end)


# ---------------------------------------------------------------------------
# Storage LLM view (strip comments + decode secrets) and disk line mapping
# ---------------------------------------------------------------------------


class TestStorageTextLlmView(unittest.TestCase):
    def test_comment_rows_dropped_visible_matches_strip(self) -> None:
        raw = "one\n[ aside ]: #\ntwo\n"
        view = storage_text_llm_view(raw)
        self.assertEqual(view.visible_for_llm, "one\ntwo\n")
        self.assertEqual(view.disk_line_start_1based, (1, 3))
        self.assertEqual(view.disk_line_end_1based, (1, 3))

    def test_resolve_maps_visible_line_to_disk_skipping_comment(self) -> None:
        raw = "visible1\n[ noise ]: #\nvisible2\nvisible3\n"
        lo, hi = resolve_storage_selection_to_disk_inclusive_lines(
            raw, _range(_sel("visible2"), _sel("visible3"))
        )
        self.assertEqual((lo, hi), (3, 4))

    def test_apply_patches_resolves_on_visible_then_splices_raw(self) -> None:
        raw = "keep\n[ c ]: #\nold\n"
        patches = [Patch(selection=_range(_sel("old")), content="new")]
        out = apply_patches_to_storage_llm_view(raw, patches)
        self.assertEqual(out, "keep\n[ c ]: #\nnew\n")

    def test_apply_patches_cursor_prepend_append(self) -> None:
        raw = "mid\n"
        patches = [
            Patch(selection=_range(_sel(START_ANCHOR)), content="HEAD"),
            Patch(selection=_range(_sel(END_ANCHOR)), content="TAIL"),
        ]
        out = apply_patches_to_storage_llm_view(raw, patches)
        self.assertEqual(out, "HEAD\nmid\nTAIL\n")

    def test_decode_secret_anchor_maps_to_storage_line(self) -> None:
        raw = "x\n<!-- ai:secret: uryyb -->\ny\n"
        lo, hi = resolve_storage_selection_to_disk_inclusive_lines(
            raw, _range(_sel("hello"))
        )
        self.assertEqual((lo, hi), (2, 2))
        out = apply_patches_to_storage_llm_view(
            raw, [Patch(selection=_range(_sel("hello")), content="there")]
        )
        self.assertIn("there", out)
        self.assertNotIn("uryyb", out)


# ---------------------------------------------------------------------------
# _split_lines behaviour (indirectly via resolve_selection)
# ---------------------------------------------------------------------------


class TestResolveSingleLine(unittest.TestCase):
    def test_unique_line_single(self) -> None:
        text = "alpha\nbeta\ngamma\n"
        resolved = resolve_selection(text, _range(_sel("beta")))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))
        self.assertEqual(resolved.lines, ("alpha", "beta", "gamma"))
        self.assertTrue(resolved.had_trailing_newline)

    def test_first_line(self) -> None:
        text = "alpha\nbeta\n"
        resolved = resolve_selection(text, _range(_sel("alpha")))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 1))

    def test_last_line_no_trailing_newline(self) -> None:
        text = "alpha\nbeta"
        resolved = resolve_selection(text, _range(_sel("beta")))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))
        self.assertFalse(resolved.had_trailing_newline)

    def test_empty_line_target(self) -> None:
        text = "alpha\n\nbeta\n"
        resolved = resolve_selection(text, _range(_sel("")))
        # The empty line is at index 1.
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))

    def test_line_with_leading_whitespace(self) -> None:
        text = "alpha\n    indented\nbeta\n"
        resolved = resolve_selection(text, _range(_sel("    indented")))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))


# ---------------------------------------------------------------------------
# Disambiguation via before/after context
# ---------------------------------------------------------------------------


class TestResolveAmbiguity(unittest.TestCase):
    def test_ambiguous_target_raises(self) -> None:
        text = "a\nfoo\nb\nfoo\nc\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("foo")))
        msg = str(ctx.exception)
        self.assertIn("ambiguous", msg)
        # error should surface the 1-based line numbers of the matches
        self.assertIn("2", msg)
        self.assertIn("4", msg)

    def test_before_context_disambiguates(self) -> None:
        text = "a\nfoo\nb\nfoo\nc\n"
        resolved = resolve_selection(
            text, _range(_sel("foo", before=("a",)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))

    def test_after_context_disambiguates(self) -> None:
        text = "a\nfoo\nb\nfoo\nc\n"
        resolved = resolve_selection(
            text, _range(_sel("foo", after=("c",)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (3, 4))

    def test_multi_line_before_context(self) -> None:
        text = "x\ny\nfoo\nz\nx\ny\nfoo\nz\n"
        # A plain ``y`` context wouldn't be enough (both foos have it); pair
        # it with another context line to force a unique match.
        resolved = resolve_selection(
            text,
            _range(_sel("foo", before=("x", "y"), after=("z", "x"))),
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (2, 3))

    def test_wrong_before_ignored_when_target_line_is_unique(self) -> None:
        text = "a\nfoo\nb\n"
        resolved = resolve_selection(text, _range(_sel("foo", before=("b",))))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))

    def test_wrong_before_ignored_for_unique_target_long_line(self) -> None:
        text = "a\nfoo\nb\nunique line\n"
        resolved = resolve_selection(
            text, _range(_sel("unique line", before=("this is not the line above",)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (3, 4))

    def test_wrong_before_no_fallback_when_target_repeats(self) -> None:
        text = "x\na\ny\na\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("a", before=("wrong",))))
        self.assertIn("no match", str(ctx.exception))

    def test_unique_substring_selects_containing_line(self) -> None:
        text = "intro\nHe startled—then he nodded, terse and wordless.\nfooter\n"
        resolved = resolve_selection(
            text,
            _range(_sel("he nodded, terse and wordless.")),
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))

    def test_substring_not_unique_across_lines_raises(self) -> None:
        text = "say hello\nlater hello world\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("hello")))
        self.assertIn("no match", str(ctx.exception))

    def test_substring_twice_same_line_not_unique(self) -> None:
        text = "ping ping\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("ping")))
        self.assertIn("no match", str(ctx.exception))

    def test_empty_line_in_context(self) -> None:
        text = "a\n\nfoo\n\nb\n"
        # foo is unique but we still verify context with an empty line works.
        resolved = resolve_selection(
            text, _range(_sel("foo", before=("",), after=("",)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (2, 3))

    def test_no_match_error_mentions_context(self) -> None:
        text = "a\nfoo\nb\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(
                text, _range(_sel("not_in_file", before=("a",)))
            )
        msg = str(ctx.exception)
        self.assertIn("before=", msg)
        self.assertIn("not_in_file", msg)


# ---------------------------------------------------------------------------
# Anchors: @@@start / @@@end
# ---------------------------------------------------------------------------


class TestResolveAnchors(unittest.TestCase):
    def test_start_anchor_in_before_forces_first_line(self) -> None:
        text = "foo\nbar\nfoo\n"
        resolved = resolve_selection(
            text, _range(_sel("foo", before=(START_ANCHOR,)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 1))

    def test_end_anchor_in_after_forces_last_line(self) -> None:
        text = "foo\nbar\nfoo\n"
        resolved = resolve_selection(
            text, _range(_sel("foo", after=(END_ANCHOR,)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (2, 3))

    def test_empty_last_line_with_end_anchor(self) -> None:
        # Document ends with an empty line (two \n in a row then none).
        text = "a\nb\n\n"
        # splitlines -> ["a", "b", ""], trailing newline preserved.
        resolved = resolve_selection(
            text, _range(_sel("", after=(END_ANCHOR,)))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (2, 3))

    def test_start_anchor_target_is_cursor_at_zero(self) -> None:
        text = "a\nb\n"
        resolved = resolve_selection(text, _range(_sel(START_ANCHOR)))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 0))
        self.assertTrue(resolved.is_cursor)

    def test_end_anchor_target_is_cursor_at_end(self) -> None:
        text = "a\nb\n"
        resolved = resolve_selection(text, _range(_sel(END_ANCHOR)))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (2, 2))
        self.assertTrue(resolved.is_cursor)

    def test_full_replace_range(self) -> None:
        text = "a\nb\nc\n"
        resolved = resolve_selection(
            text, _range(_sel(START_ANCHOR), _sel(END_ANCHOR))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 3))

    def test_start_anchor_target_cannot_have_context(self) -> None:
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(
                "a\nb\n",
                _range(_sel(START_ANCHOR, before=("x",))),
            )
        self.assertIn("cursor target cannot have", str(ctx.exception))

    def test_start_anchor_must_be_first_in_before(self) -> None:
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(
                "a\nb\n",
                _range(_sel("b", before=("a", START_ANCHOR))),
            )
        self.assertIn("must be the first element", str(ctx.exception))

    def test_end_anchor_must_be_last_in_after(self) -> None:
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(
                "a\nb\n",
                _range(_sel("a", after=(END_ANCHOR, "b"))),
            )
        self.assertIn("must be the last element", str(ctx.exception))

    def test_start_anchor_not_allowed_in_after(self) -> None:
        with self.assertRaises(SelectionError):
            resolve_selection(
                "a\n",
                _range(_sel("a", after=(START_ANCHOR,))),
            )

    def test_end_anchor_not_allowed_in_before(self) -> None:
        with self.assertRaises(SelectionError):
            resolve_selection(
                "a\n",
                _range(_sel("a", before=(END_ANCHOR,))),
            )

    def test_empty_document_start_anchor_cursor(self) -> None:
        resolved = resolve_selection("", _range(_sel(START_ANCHOR)))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 0))

    def test_empty_document_end_anchor_cursor(self) -> None:
        resolved = resolve_selection("", _range(_sel(END_ANCHOR)))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 0))

    def test_empty_document_target_fails(self) -> None:
        with self.assertRaises(SelectionError):
            resolve_selection("", _range(_sel("anything")))


# ---------------------------------------------------------------------------
# Ranges: start + end selectors
# ---------------------------------------------------------------------------


class TestResolveRange(unittest.TestCase):
    def test_basic_range(self) -> None:
        text = "a\nb\nc\nd\ne\n"
        resolved = resolve_selection(
            text, _range(_sel("b"), _sel("d"))
        )
        # Inclusive range b..d -> slice 1:4
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 4))

    def test_range_single_line(self) -> None:
        text = "a\nb\nc\n"
        resolved = resolve_selection(text, _range(_sel("b"), _sel("b")))
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 2))

    def test_range_start_to_end_anchor(self) -> None:
        text = "a\nb\nc\n"
        resolved = resolve_selection(
            text, _range(_sel("b"), _sel(END_ANCHOR))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 3))

    def test_range_start_anchor_to_line(self) -> None:
        text = "a\nb\nc\n"
        resolved = resolve_selection(
            text, _range(_sel(START_ANCHOR), _sel("b"))
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (0, 2))

    def test_range_out_of_order_raises(self) -> None:
        text = "a\nb\nc\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("c"), _sel("a")))
        self.assertIn("out of order", str(ctx.exception))

    def test_range_with_disambiguated_ends(self) -> None:
        text = "x\nrepeat\ny\nrepeat\nz\n"
        resolved = resolve_selection(
            text,
            _range(
                _sel("repeat", before=("x",)),
                _sel("repeat", before=("y",)),
            ),
        )
        self.assertEqual((resolved.slice_start, resolved.slice_end), (1, 4))

    def test_end_target_not_found(self) -> None:
        text = "a\nb\nc\n"
        with self.assertRaises(SelectionError) as ctx:
            resolve_selection(text, _range(_sel("a"), _sel("nope")))
        self.assertIn("end:", str(ctx.exception))


# ---------------------------------------------------------------------------
# apply_patch — replacement and insertion
# ---------------------------------------------------------------------------


class TestApplyPatchReplace(unittest.TestCase):
    def test_replace_single_line(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(selection=_range(_sel("b")), content="B")
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nB\nc\n")

    def test_replace_range(self) -> None:
        text = "a\nb\nc\nd\n"
        patch = Patch(
            selection=_range(_sel("b"), _sel("c")),
            content="X\nY",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nX\nY\nd\n")

    def test_replace_with_empty_deletes(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(selection=_range(_sel("b")), content="")
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nc\n")

    def test_replace_range_with_empty_deletes(self) -> None:
        text = "a\nb\nc\nd\n"
        patch = Patch(
            selection=_range(_sel("b"), _sel("c")),
            content="",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nd\n")

    def test_replace_preserves_trailing_newline_state(self) -> None:
        text_with = "a\nb\n"
        text_without = "a\nb"
        patch = Patch(selection=_range(_sel("a")), content="A")
        self.assertEqual(apply_patch(text_with, patch), "A\nb\n")
        self.assertEqual(apply_patch(text_without, patch), "A\nb")

    def test_full_replace_with_anchors(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(
            selection=_range(_sel(START_ANCHOR), _sel(END_ANCHOR)),
            content="new content\nhere",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "new content\nhere\n")

    def test_full_replace_empty_content(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(
            selection=_range(_sel(START_ANCHOR), _sel(END_ANCHOR)),
            content="",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "\n")

    def test_replace_content_trailing_newline_is_swallowed(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(selection=_range(_sel("b")), content="B\n")
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nB\nc\n")

    def test_content_with_blank_interior_line(self) -> None:
        text = "a\nb\nc\n"
        patch = Patch(selection=_range(_sel("b")), content="B1\n\nB2")
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nB1\n\nB2\nc\n")


class TestApplyPatchInsert(unittest.TestCase):
    def test_prepend_with_start_anchor(self) -> None:
        text = "a\nb\n"
        patch = Patch(
            selection=_range(_sel(START_ANCHOR)),
            content="HEADER",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "HEADER\na\nb\n")

    def test_append_with_end_anchor(self) -> None:
        text = "a\nb\n"
        patch = Patch(
            selection=_range(_sel(END_ANCHOR)),
            content="FOOTER",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nb\nFOOTER\n")

    def test_append_multiline(self) -> None:
        text = "a\nb\n"
        patch = Patch(
            selection=_range(_sel(END_ANCHOR)),
            content="c\nd",
        )
        result = apply_patch(text, patch)
        self.assertEqual(result, "a\nb\nc\nd\n")

    def test_insert_into_empty_document(self) -> None:
        patch = Patch(
            selection=_range(_sel(START_ANCHOR)),
            content="hello",
        )
        result = apply_patch("", patch)
        self.assertEqual(result, "hello")

    def test_cursor_at_end_empty_doc_same_as_start(self) -> None:
        patch = Patch(
            selection=_range(_sel(END_ANCHOR)),
            content="hello",
        )
        result = apply_patch("", patch)
        self.assertEqual(result, "hello")


# ---------------------------------------------------------------------------
# apply_patches — multiple patches applied sequentially
# ---------------------------------------------------------------------------


class TestApplyPatchesSequential(unittest.TestCase):
    def test_two_independent_patches(self) -> None:
        text = "a\nb\nc\nd\n"
        patches = [
            Patch(selection=_range(_sel("a")), content="A"),
            Patch(selection=_range(_sel("d")), content="D"),
        ]
        result = apply_patches(text, patches)
        self.assertEqual(result, "A\nb\nc\nD\n")

    def test_later_patch_sees_earlier_changes(self) -> None:
        text = "a\nb\nc\n"
        patches = [
            Patch(selection=_range(_sel("b")), content="BEE"),
            # After patch 1, "BEE" exists; targeting "b" would now fail.
            Patch(selection=_range(_sel("BEE")), content="BE"),
        ]
        result = apply_patches(text, patches)
        self.assertEqual(result, "a\nBE\nc\n")

    def test_later_patch_targeting_vanished_line_fails(self) -> None:
        text = "a\nb\nc\n"
        patches = [
            Patch(selection=_range(_sel("b")), content="BEE"),
            Patch(selection=_range(_sel("b")), content="X"),  # b no longer exists
        ]
        with self.assertRaises(SelectionError) as ctx:
            apply_patches(text, patches)
        self.assertIn("patch #2", str(ctx.exception))
        self.assertIn("no match", str(ctx.exception))

    def test_ambiguity_error_reports_patch_number(self) -> None:
        text = "a\nfoo\nb\nfoo\nc\n"
        patches = [
            Patch(selection=_range(_sel("a")), content="AAA"),
            Patch(selection=_range(_sel("foo")), content="X"),
        ]
        with self.assertRaises(SelectionError) as ctx:
            apply_patches(text, patches)
        self.assertIn("patch #2", str(ctx.exception))
        self.assertIn("ambiguous", str(ctx.exception))

    def test_prepend_then_append(self) -> None:
        patches = [
            Patch(selection=_range(_sel(START_ANCHOR)), content="HEAD"),
            Patch(selection=_range(_sel(END_ANCHOR)), content="TAIL"),
        ]
        result = apply_patches("body\n", patches)
        self.assertEqual(result, "HEAD\nbody\nTAIL\n")

    def test_empty_patches_is_identity(self) -> None:
        text = "a\nb\n"
        self.assertEqual(apply_patches(text, []), text)


# ---------------------------------------------------------------------------
# parse_patches — tool-call payload shape
# ---------------------------------------------------------------------------


class TestParsePatches(unittest.TestCase):
    def test_parse_single_line_patch(self) -> None:
        patches = parse_patches(
            [
                {
                    "start": {"target": "hello"},
                    "content": "hi",
                }
            ]
        )
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].selection.start.target, "hello")
        self.assertIsNone(patches[0].selection.end)
        self.assertEqual(patches[0].content, "hi")

    def test_parse_range_patch(self) -> None:
        patches = parse_patches(
            [
                {
                    "start": {"target": "a", "after": ["b"]},
                    "end": {"target": "c", "before": ["b"]},
                    "content": "new",
                }
            ]
        )
        self.assertEqual(patches[0].selection.start.target, "a")
        self.assertEqual(patches[0].selection.start.after, ("b",))
        assert patches[0].selection.end is not None
        self.assertEqual(patches[0].selection.end.target, "c")
        self.assertEqual(patches[0].selection.end.before, ("b",))

    def test_parse_anchor_patch(self) -> None:
        patches = parse_patches(
            [
                {
                    "start": {"target": START_ANCHOR},
                    "end": {"target": END_ANCHOR},
                    "content": "",
                }
            ]
        )
        self.assertEqual(patches[0].selection.start.target, START_ANCHOR)
        assert patches[0].selection.end is not None
        self.assertEqual(patches[0].selection.end.target, END_ANCHOR)

    def test_parse_defaults_content_to_empty(self) -> None:
        patches = parse_patches([{"start": {"target": "a"}}])
        self.assertEqual(patches[0].content, "")

    def test_parse_none_returns_empty_list(self) -> None:
        self.assertEqual(parse_patches(None), [])

    def test_parse_non_list_raises(self) -> None:
        with self.assertRaises(SelectionError):
            parse_patches({"not": "a list"})  # type: ignore[arg-type]

    def test_parse_missing_start_raises(self) -> None:
        with self.assertRaises(SelectionError) as ctx:
            parse_patches([{"content": "x"}])
        self.assertIn("start", str(ctx.exception))
        self.assertIn("patch #1", str(ctx.exception))

    def test_parse_non_string_target_raises(self) -> None:
        with self.assertRaises(SelectionError):
            parse_patches([{"start": {"target": 123}}])

    def test_parse_non_list_context_raises(self) -> None:
        with self.assertRaises(SelectionError):
            parse_patches([{"start": {"target": "x", "before": "y"}}])

    def test_parse_non_string_content_raises(self) -> None:
        with self.assertRaises(SelectionError):
            parse_patches([{"start": {"target": "x"}, "content": 42}])

    def test_parse_preserves_patch_order(self) -> None:
        patches = parse_patches(
            [
                {"start": {"target": "a"}, "content": "A"},
                {"start": {"target": "b"}, "content": "B"},
                {"start": {"target": "c"}, "content": "C"},
            ]
        )
        self.assertEqual([p.content for p in patches], ["A", "B", "C"])


# ---------------------------------------------------------------------------
# roundtrip — patches preserve unaffected content exactly
# ---------------------------------------------------------------------------


class TestRoundtrip(unittest.TestCase):
    def test_apply_empty_patchset_is_identity(self) -> None:
        texts = [
            "",
            "a\n",
            "a\nb",
            "a\n\nb\n",
            "line with trailing whitespace  \n",
            "\n\n\n",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(apply_patches(text, []), text)

    def test_noop_replacement_preserves_text(self) -> None:
        text = "alpha\nbeta\ngamma\n"
        patch = Patch(selection=_range(_sel("beta")), content="beta")
        self.assertEqual(apply_patch(text, patch), text)

    def test_unaffected_lines_are_untouched(self) -> None:
        text = "one\ntwo\nthree\nfour\n"
        patch = Patch(selection=_range(_sel("three")), content="THREE")
        self.assertEqual(apply_patch(text, patch), "one\ntwo\nTHREE\nfour\n")
