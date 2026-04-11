"""Tests for the shared summary-block formatter in lens.core.operators.session."""

from __future__ import annotations

import unittest

from lens.core.operators.session import (
    MAX_SUMMARY_TITLE_WORDS,
    format_summary_block,
    slug_to_title,
)


class TestSlugToTitle(unittest.TestCase):
    def test_simple_slug(self) -> None:
        self.assertEqual(slug_to_title("amy-dream"), "Amy Dream")

    def test_single_word(self) -> None:
        self.assertEqual(slug_to_title("epilogue"), "Epilogue")

    def test_underscore_slug(self) -> None:
        self.assertEqual(slug_to_title("battle_of_glenhaven"), "Battle Of Glenhaven")

    def test_strips_section_prefix(self) -> None:
        self.assertEqual(slug_to_title("section-chapter-one"), "Chapter One")

    def test_strips_play_prefix(self) -> None:
        self.assertEqual(slug_to_title("play-amy-dream"), "Amy Dream")

    def test_strips_advance_day_prefix(self) -> None:
        self.assertEqual(slug_to_title("advance-day-3"), "3")

    def test_fallback_when_no_words(self) -> None:
        self.assertEqual(slug_to_title("section-"), "section-")


class TestFormatSummaryBlock(unittest.TestCase):
    def test_happy_path_with_plain_title_first_line(self) -> None:
        raw = "Amy's Dream\n\nShe wakes in an unfamiliar room. The door is locked."
        block, title_from_raw = format_summary_block("amy-dream", raw)
        self.assertTrue(title_from_raw)
        self.assertEqual(
            block,
            (
                "<!-- section:amy-dream -->\n"
                "\n"
                "### Amy's Dream\n"
                "\n"
                "> She wakes in an unfamiliar room. The door is locked."
            ),
        )

    def test_strips_hash_markers_from_title(self) -> None:
        raw = "### Amy's Dream\n\nBody text here."
        block, title_from_raw = format_summary_block("amy-dream", raw)
        self.assertTrue(title_from_raw)
        self.assertIn("### Amy's Dream", block)
        # No double-hashes
        self.assertNotIn("### ### ", block)

    def test_strips_bold_markers_from_title(self) -> None:
        raw = "**Amy's Dream**\n\nBody."
        block, title_from_raw = format_summary_block("amy-dream", raw)
        self.assertTrue(title_from_raw)
        self.assertIn("### Amy's Dream", block)

    def test_section_html_comment_prefix_and_slug_in_comment(self) -> None:
        raw = "Title Line\n\nBody."
        block, _ = format_summary_block("my-slug", raw)
        self.assertTrue(block.startswith("<!-- section:my-slug -->\n\n### "))

    def test_blank_line_between_comment_and_header(self) -> None:
        raw = "Title\n\nBody text."
        block, _ = format_summary_block("slug", raw)
        lines = block.split("\n")
        self.assertEqual(lines[0], "<!-- section:slug -->")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "### Title")
        self.assertEqual(lines[3], "")

    def test_multi_line_body_all_blockquoted(self) -> None:
        raw = "Title\n\nLine one.\nLine two.\nLine three."
        block, _ = format_summary_block("slug", raw)
        self.assertIn("> Line one.", block)
        self.assertIn("> Line two.", block)
        self.assertIn("> Line three.", block)

    def test_blank_lines_in_body_remain_unquoted(self) -> None:
        raw = "Title\n\nFirst paragraph.\n\nSecond paragraph."
        block, _ = format_summary_block("slug", raw)
        lines = block.split("\n")
        # Find the body portion (after title + blank line)
        # Expected: first-para line, blank line, second-para line — blank not quoted.
        self.assertIn("> First paragraph.", lines)
        self.assertIn("> Second paragraph.", lines)
        blank_indices = [i for i, ln in enumerate(lines) if ln == ""]
        # At least the separator blank between header and body plus the
        # blank line between the two body paragraphs.
        self.assertGreaterEqual(len(blank_indices), 2)

    def test_existing_blockquote_markers_not_doubled(self) -> None:
        raw = "Title\n\n> Already quoted.\n> Still quoted."
        block, _ = format_summary_block("slug", raw)
        self.assertIn("> Already quoted.", block)
        self.assertIn("> Still quoted.", block)
        self.assertNotIn("> > ", block)

    def test_title_longer_than_max_falls_back_to_slug(self) -> None:
        long = " ".join(["word"] * (MAX_SUMMARY_TITLE_WORDS + 1))
        raw = f"{long}\n\nBody goes here."
        block, title_from_raw = format_summary_block("amy-dream", raw)
        self.assertFalse(title_from_raw)
        self.assertIn("### Amy Dream", block)
        # The too-long first line should be kept as body content (blockquoted)
        self.assertIn(f"> {long}", block)

    def test_exactly_max_words_is_accepted(self) -> None:
        exact = " ".join(["word"] * MAX_SUMMARY_TITLE_WORDS)
        raw = f"{exact}\n\nBody."
        block, title_from_raw = format_summary_block("slug", raw)
        self.assertTrue(title_from_raw)
        self.assertIn(f"### {exact}", block)

    def test_empty_summary_still_produces_block(self) -> None:
        block, title_from_raw = format_summary_block("amy-dream", "")
        self.assertFalse(title_from_raw)
        self.assertIn("<!-- section:amy-dream -->", block)
        self.assertIn("### Amy Dream", block)

    def test_single_line_raw_used_as_title_when_short(self) -> None:
        raw = "All quiet."
        block, title_from_raw = format_summary_block("aside", raw)
        self.assertTrue(title_from_raw)
        self.assertIn("### All quiet.", block)
        # No body lines — body trimmed down to nothing.
        # The block should still be well-formed.
        self.assertTrue(block.startswith("<!-- section:aside -->\n\n### All quiet.\n"))

    def test_trailing_colon_stripped_from_title(self) -> None:
        raw = "Chapter One:\n\nBody."
        block, title_from_raw = format_summary_block("ch1", raw)
        self.assertTrue(title_from_raw)
        self.assertIn("### Chapter One", block)
        self.assertNotIn("### Chapter One:", block)

    def test_leading_blank_lines_in_raw_are_skipped(self) -> None:
        raw = "\n\n\nTitle\n\nBody."
        block, title_from_raw = format_summary_block("slug", raw)
        self.assertTrue(title_from_raw)
        self.assertIn("### Title", block)
