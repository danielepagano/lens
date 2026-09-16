"""Tests for the shared summary-block formatter in lens.core.operators.session."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.annotations import strip_markdown_comments
from lens.core.context import CrawlResult
from lens.core.llm_trace import split_trace_blocks
from lens.core.operators.session import (
    MAX_SUMMARY_TITLE_WORDS,
    SummaryTitleError,
    build_summary_messages,
    format_summary_block,
    slug_for_summary_prompt,
)


class TestSlugForSummaryPrompt(unittest.TestCase):
    def test_strips_known_prefixes(self) -> None:
        self.assertEqual(slug_for_summary_prompt("play-amy-dream"), "amy-dream")
        self.assertEqual(slug_for_summary_prompt("section-chapter-one"), "chapter-one")
        self.assertEqual(slug_for_summary_prompt("advance-day-3"), "3")

    def test_unprefixed_unchanged(self) -> None:
        self.assertEqual(slug_for_summary_prompt("amy-dream"), "amy-dream")
        self.assertEqual(slug_for_summary_prompt("epilogue"), "epilogue")


class TestBuildSummaryMessages(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\n', encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_appends_guidance_to_user_instruction(self) -> None:
        crawl = CrawlResult.from_text_fields(
            project_root=self.root,
            knowledge=[],
            previous_summaries=[],
            current_content=None,
        )
        guidance_token = "summary-guidance-test-token-a1b2"
        msgs = build_summary_messages(
            crawl,
            "passage to summarize",
            slug="section-ch1",
            summary_guidance=guidance_token,
        )
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        user = msgs[1]["content"]
        self.assertIn("passage to summarize", user)
        self.assertIn(guidance_token, user)

    def test_omits_guidance_block_when_none(self) -> None:
        crawl = CrawlResult.from_text_fields(
            project_root=self.root,
            knowledge=[],
            previous_summaries=[],
            current_content=None,
        )
        guidance_token = "summary-guidance-test-token-c3d4"
        msgs_none = build_summary_messages(
            crawl,
            "body",
            slug="x",
            summary_guidance=None,
        )
        self.assertNotIn(guidance_token, msgs_none[1]["content"])
        msgs_with = build_summary_messages(
            crawl,
            "body",
            slug="x",
            summary_guidance=guidance_token,
        )
        self.assertIn(guidance_token, msgs_with[1]["content"])


class TestFormatSummaryBlock(unittest.TestCase):
    def test_happy_path_with_plain_title_first_line(self) -> None:
        raw = "Amy's Dream\n\nShe wakes in an unfamiliar room. The door is locked."
        block = format_summary_block("amy-dream", raw)
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
        block = format_summary_block("amy-dream", raw)
        self.assertIn("### Amy's Dream", block)
        self.assertNotIn("### ### ", block)

    def test_strips_bold_markers_from_title(self) -> None:
        raw = "**Amy's Dream**\n\nBody."
        block = format_summary_block("amy-dream", raw)
        self.assertIn("### Amy's Dream", block)

    def test_section_html_comment_uses_full_storage_slug(self) -> None:
        raw = "Title Line\n\nBody."
        block = format_summary_block("play-amy-dream", raw)
        self.assertTrue(block.startswith("<!-- section:play-amy-dream -->\n\n### "))

    def test_blank_line_between_comment_and_header(self) -> None:
        raw = "Title\n\nBody text."
        block = format_summary_block("slug", raw)
        lines = block.split("\n")
        self.assertEqual(lines[0], "<!-- section:slug -->")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "### Title")
        self.assertEqual(lines[3], "")

    def test_multi_line_body_all_blockquoted(self) -> None:
        raw = "Title\n\nLine one.\nLine two.\nLine three."
        block = format_summary_block("slug", raw)
        self.assertIn("> Line one.", block)
        self.assertIn("> Line two.", block)
        self.assertIn("> Line three.", block)

    def test_blank_lines_inside_body_use_quoted_empty_lines(self) -> None:
        raw = "Title\n\nFirst paragraph.\n\nSecond paragraph."
        block = format_summary_block("slug", raw)
        self.assertEqual(
            block,
            (
                "<!-- section:slug -->\n"
                "\n"
                "### Title\n"
                "\n"
                "> First paragraph.\n"
                "> \n"
                "> Second paragraph."
            ),
        )

    def test_existing_blockquote_markers_not_doubled(self) -> None:
        raw = "Title\n\n> Already quoted.\n> Still quoted."
        block = format_summary_block("slug", raw)
        self.assertIn("> Already quoted.", block)
        self.assertIn("> Still quoted.", block)
        self.assertNotIn("> > ", block)

    def test_title_longer_than_max_raises(self) -> None:
        long = " ".join(["word"] * (MAX_SUMMARY_TITLE_WORDS + 1))
        raw = f"{long}\n\nBody goes here."
        with self.assertRaises(SummaryTitleError):
            format_summary_block("amy-dream", raw)

    def test_exactly_max_words_is_accepted(self) -> None:
        exact = " ".join(["word"] * MAX_SUMMARY_TITLE_WORDS)
        raw = f"{exact}\n\nBody."
        block = format_summary_block("slug", raw)
        self.assertIn(f"### {exact}", block)

    def test_empty_summary_raises(self) -> None:
        with self.assertRaises(SummaryTitleError):
            format_summary_block("amy-dream", "")

    def test_single_line_raw_used_as_title_when_short(self) -> None:
        raw = "All quiet."
        block = format_summary_block("aside", raw)
        self.assertIn("### All quiet.", block)
        self.assertTrue(
            block.startswith("<!-- section:aside -->\n\n### All quiet.\n")
        )

    def test_trailing_colon_stripped_from_title(self) -> None:
        raw = "Chapter One:\n\nBody."
        block = format_summary_block("ch1", raw)
        self.assertIn("### Chapter One", block)
        self.assertNotIn("### Chapter One:", block)

    def test_leading_blank_lines_in_raw_are_skipped(self) -> None:
        raw = "\n\n\nTitle\n\nBody."
        block = format_summary_block("slug", raw)
        self.assertIn("### Title", block)


_TRACE = (
    "[llm-trace\n"
    "  model: deepseek/deepseek-v4.1-flash\n"
    "  elapsed_ms: 18310\n"
    "  usage:\n"
    "    prompt_tokens: 12325\n"
    "]: #"
)


class TestSummaryTraceNotQuoted(unittest.TestCase):
    """The summary's own ``[llm-trace …]: #`` must stay outside the blockquote.

    Quoted, it survives ``strip_markdown_comments`` (which anchors on ``^\\s*\\[``)
    and reaches the model inside the summary every descendant node reads.
    """

    def _formatted(self) -> str:
        raw = f"The Climb\n\nFour days late on a three-day climb.\n\n{_TRACE}\n"
        return format_summary_block("play-climb", raw)

    def test_trace_emitted_at_column_zero_after_the_body(self) -> None:
        block = self._formatted()
        self.assertEqual(
            block,
            (
                "<!-- section:play-climb -->\n"
                "\n"
                "### The Climb\n"
                "\n"
                "> Four days late on a three-day climb.\n"
                "\n"
                f"{_TRACE}"
            ),
        )

    def test_no_trace_line_is_blockquoted(self) -> None:
        for line in self._formatted().split("\n"):
            if line.startswith(">"):
                self.assertNotIn("llm-trace", line)
                self.assertNotIn("prompt_tokens", line)

    def test_stripper_removes_the_trace_from_the_block(self) -> None:
        stripped = strip_markdown_comments(self._formatted())
        self.assertNotIn("llm-trace", stripped)
        self.assertNotIn("elapsed_ms", stripped)
        self.assertIn("> Four days late on a three-day climb.", stripped)

    def test_title_comes_from_prose_when_body_is_only_a_trace(self) -> None:
        # A generation that produced nothing but telemetry produced nothing:
        # the title rule must fail so the caller retries, not title the block
        # "[llm-trace".
        with self.assertRaises(SummaryTitleError):
            format_summary_block("play-climb", f"{_TRACE}\n")


class TestSplitTraceBlocks(unittest.TestCase):
    def test_text_without_trace_is_unchanged(self) -> None:
        text = "Title\n\nBody with a [reference]: # looking line."
        remaining, blocks = split_trace_blocks(text)
        self.assertEqual(remaining, text)
        self.assertEqual(blocks, [])

    def test_trailing_trace_is_lifted(self) -> None:
        remaining, blocks = split_trace_blocks(f"Body.\n\n{_TRACE}\n")
        self.assertEqual(remaining.strip(), "Body.")
        self.assertEqual(blocks, [_TRACE + "\n"])

    def test_unterminated_trace_consumes_to_end(self) -> None:
        # Everything from the opener on is telemetry; leaking half a block into
        # the quoted body is the failure this guards.
        remaining, blocks = split_trace_blocks("Body.\n\n[llm-trace\n  model: x\n")
        self.assertEqual(remaining.strip(), "Body.")
        self.assertEqual(len(blocks), 1)
        self.assertIn("model: x", blocks[0])

    def test_multiple_traces_all_lifted(self) -> None:
        remaining, blocks = split_trace_blocks(f"{_TRACE}\nBody.\n{_TRACE}\n")
        self.assertEqual(remaining.strip(), "Body.")
        self.assertEqual(len(blocks), 2)
