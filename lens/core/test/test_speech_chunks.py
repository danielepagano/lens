"""Tests for narrative TTS chunking helpers."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode
from lens.core.exceptions import LensException
from lens.core.speech.chunks import (
    TTS_CHUNK_MAX_CHARS,
    TTS_CHUNK_REVISION,
    TTS_SUBCHUNK_SOFT_MIN_CHARS,
    chunk_id,
    chunks_by_kept_line,
    chunks_for_node_text,
    is_eligible_tts_line,
    slice_storage_text_by_disk_lines,
    strip_fenced_code_blocks,
    strip_for_tts,
    tts_cache_mount_prefix,
    tts_chunks_for_eligible_trimmed_line,
)


class TestChunkId(unittest.TestCase):
    def test_one_word(self) -> None:
        line = "Hello."
        digest = hashlib.md5(line.strip().encode()).hexdigest()
        cid = chunk_id(1, line)
        self.assertEqual(cid, f"chk1-hello--{digest}")

    def test_two_words(self) -> None:
        line = "Hello world"
        digest = hashlib.md5(line.encode()).hexdigest()
        cid = chunk_id(1, line)
        self.assertEqual(cid, f"chk1-hello--{digest}--world")

    def test_three_plus_words(self) -> None:
        line = "Hello world middle tail last"
        digest = hashlib.md5(line.encode()).hexdigest()
        cid = chunk_id(1, line)
        self.assertEqual(cid, f"chk1-hello-world--{digest}--last")

    def test_revision_constant(self) -> None:
        self.assertEqual(TTS_CHUNK_REVISION, 1)

    def test_size_constants(self) -> None:
        self.assertEqual(TTS_CHUNK_MAX_CHARS, 350)
        self.assertEqual(TTS_SUBCHUNK_SOFT_MIN_CHARS, 70)


class TestEligibility(unittest.TestCase):
    def test_skips_empty_punct_numbers_link(self) -> None:
        self.assertFalse(is_eligible_tts_line(""))
        self.assertFalse(is_eligible_tts_line("   "))
        self.assertFalse(is_eligible_tts_line("..."))
        self.assertFalse(is_eligible_tts_line("42"))
        self.assertFalse(is_eligible_tts_line("3.14"))
        self.assertFalse(is_eligible_tts_line("![x](y)"))
        self.assertFalse(is_eligible_tts_line("[a](https://e)"))

    def test_keeps_prose(self) -> None:
        self.assertTrue(is_eligible_tts_line("The door creaks open."))
        self.assertTrue(is_eligible_tts_line("Room 101 has a story."))


class TestStripForTts(unittest.TestCase):
    def test_attributed_blockquote(self) -> None:
        self.assertEqual(
            strip_for_tts("> [GM] The rain falls."),
            "The rain falls.",
        )

    def test_heading_and_bold(self) -> None:
        t = strip_for_tts("### **Bold** title")
        self.assertNotIn("#", t)
        self.assertNotIn("*", t)
        self.assertIn("Bold", t)


class TestChunksForNodeText(unittest.TestCase):
    def test_skips_front_matter_and_annotation_and_html(self) -> None:
        raw = """[\n    kb_pin: []\n]: #

Hello visible.

<!--
secret
-->

[write:id]: #

Also here.

"""
        chunks = chunks_for_node_text(raw)
        texts = [c.speak_text for c in chunks]
        self.assertIn("Hello visible.", texts)
        self.assertIn("Also here.", texts)
        self.assertEqual(len(chunks), 2)
        lines = [c.source_kept_line_1 for c in chunks]
        self.assertEqual(len(lines), len(set(lines)))
        self.assertLess(lines[0], lines[1])

    def test_skips_punctuation_only_line(self) -> None:
        raw = "Hello.\n\n---\n\nGoodbye."
        chunks = chunks_for_node_text(raw)
        self.assertEqual([c.speak_text for c in chunks], ["Hello.", "Goodbye."])

    def test_skips_fenced_code_block_lines(self) -> None:
        raw = """Before.

```python
def foo():
    pass
```

After.
"""
        chunks = chunks_for_node_text(raw)
        self.assertEqual([c.speak_text for c in chunks], ["Before.", "After."])
        self.assertFalse(any("def foo" in c.speak_text for c in chunks))

    def test_skips_fenced_yaml_info_string(self) -> None:
        raw = """Narration.

```yaml
kb_pin:
  - person.a
```

More narration.
"""
        chunks = chunks_for_node_text(raw)
        self.assertEqual([c.speak_text for c in chunks], ["Narration.", "More narration."])
        self.assertFalse(any("kb_pin" in c.speak_text for c in chunks))

    def test_fenced_body_line_starting_with_triple_backtick_does_not_close(self) -> None:
        raw = """Start.

```yaml
foo: |
  ```not-a-closer
bar: 1
```

End.
"""
        stripped = strip_fenced_code_blocks(raw)
        self.assertNotIn("foo:", stripped)
        self.assertNotIn("bar:", stripped)
        chunks = chunks_for_node_text(raw)
        self.assertEqual([c.speak_text for c in chunks], ["Start.", "End."])

    def test_strip_fenced_splitlines_handles_cr(self) -> None:
        raw = "Say.\r\n\r\n```\r\nx\r\n```\r\n\r\nDone.\r\n"
        self.assertEqual(
            [c.speak_text for c in chunks_for_node_text(raw)],
            ["Say.", "Done."],
        )

    def test_strip_fenced_empties_orphan_opener_line(self) -> None:
        raw = "```\nno closing fence\n"
        self.assertEqual(strip_fenced_code_blocks(raw), "\nno closing fence\n")
        self.assertEqual(strip_fenced_code_blocks("```tool-call\n"), "\n")

    def test_strip_fenced_preserves_line_count(self) -> None:
        raw = "Say.\n\n```\nx\ny\n```\n\nDone.\n"
        stripped = strip_fenced_code_blocks(raw)
        self.assertEqual(raw.count("\n"), stripped.count("\n"))


class TestSliceStorageLines(unittest.TestCase):
    def test_single_line_address(self) -> None:
        raw = "a\nb\nc\nd\n"
        self.assertEqual(slice_storage_text_by_disk_lines(raw, 3, None), "c")

    def test_line_range_inclusive(self) -> None:
        raw = "l1\nl2\nl3\nl4\n"
        self.assertEqual(
            slice_storage_text_by_disk_lines(raw, 2, 3),
            "l2\nl3",
        )

    def test_invalid_range_raises(self) -> None:
        with self.assertRaises(LensException):
            slice_storage_text_by_disk_lines("a\nb\n", 3, 1)


class TestChunksLineSlice(unittest.TestCase):
    def test_slice_limits_chunks(self) -> None:
        raw = "One.\nTwo.\nThree.\n"
        all_three = chunks_for_node_text(raw)
        self.assertEqual(len(all_three), 3)
        mid = chunks_for_node_text(raw, line_start_1=2, line_end_1=2)
        self.assertEqual(len(mid), 1)
        self.assertEqual(mid[0].speak_text, "Two.")
        self.assertEqual(mid[0].source_kept_line_1, 2)

    def test_long_line_in_slice_shares_kept_line_index(self) -> None:
        long_line = "a" * 180 + "." + "b" * 180
        raw = "skip.\n" + long_line + "\n"
        mid = chunks_for_node_text(raw, line_start_1=2, line_end_1=2)
        self.assertEqual(len(mid), 2)
        self.assertEqual(mid[0].source_kept_line_1, 2)
        self.assertEqual(mid[1].source_kept_line_1, 2)

    def test_chunks_emit_raw_on_disk_lines_with_html_comment_above(self) -> None:
        raw = (
            "<!--\n"
            "secret\n"
            "-->\n"
            "Hello.\n"
        )
        chunks = chunks_for_node_text(raw)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].speak_text, "Hello.")
        self.assertEqual(chunks[0].source_kept_line_1, 4)

    def test_chunks_emit_raw_on_disk_lines_with_fenced_block_above(self) -> None:
        raw = (
            "```python\n"
            "x = 1\n"
            "```\n"
            "After.\n"
        )
        chunks = chunks_for_node_text(raw)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].speak_text, "After.")
        self.assertEqual(chunks[0].source_kept_line_1, 4)


class TestSubchunking(unittest.TestCase):
    def test_short_line_single_chunk(self) -> None:
        chunks = chunks_for_node_text("Hello there.\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].raw_line, "Hello there.")
        self.assertEqual(chunks[0].source_kept_line_1, 1)

    def test_long_line_splits_at_sentence(self) -> None:
        long_line = "a" * 180 + "." + "b" * 180
        chunks = chunks_for_node_text(long_line + "\n")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(c.raw_line) <= TTS_CHUNK_MAX_CHARS for c in chunks))
        self.assertEqual(chunks[0].source_kept_line_1, chunks[1].source_kept_line_1)

    def test_no_punctuation_stays_single_oversize_chunk(self) -> None:
        long_line = "x" * 400
        chunks = chunks_for_node_text(long_line + "\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0].raw_line), 400)
        self.assertGreater(len(chunks[0].raw_line), TTS_CHUNK_MAX_CHARS)

    def test_ellipsis_has_no_period_boundaries_single_chunk(self) -> None:
        left, right = "y" * 200, "z" * 200
        long_line = left + "..." + right
        self.assertGreater(len(long_line), TTS_CHUNK_MAX_CHARS)
        chunks = chunks_for_node_text(long_line + "\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].raw_line, long_line)

    def test_period_preferred_over_more_centered_colon(self) -> None:
        long_line = "a" * 79 + "." + "b" * 119 + ":" + "c" * 200
        self.assertGreater(len(long_line), TTS_CHUNK_MAX_CHARS)
        chunks = chunks_for_node_text(long_line + "\n")
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].raw_line.endswith("."))

    def test_soft_min_falls_back_when_all_cuts_tight(self) -> None:
        long_line = (
            "x" * 10
            + "."
            + "y" * 350
            + "."
            + "z" * 40
        )
        self.assertGreater(len(long_line), TTS_CHUNK_MAX_CHARS)
        chunks = chunks_for_node_text(long_line + "\n")
        self.assertGreater(len(chunks), 1)

    def test_chunks_by_kept_line_groups_subchunks(self) -> None:
        long_line = "p" * 180 + "." + "q" * 180
        raw = "First.\n" + long_line + "\nLast.\n"
        chunks = chunks_for_node_text(raw)
        by_line = chunks_by_kept_line(chunks)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(len(by_line[2]), 2)
        self.assertEqual(len(by_line[1]), 1)
        self.assertEqual(len(by_line[3]), 1)


def _assert_joined_raw_matches_trimmed(trimmed: str, line_1: int = 1) -> None:
    chunks = tts_chunks_for_eligible_trimmed_line(trimmed, line_1)
    joined = "".join(c.raw_line for c in chunks)
    assert joined == trimmed, (joined, trimmed)


class TestTtsChunksEligibleTrimmedLine(unittest.TestCase):
    def test_join_invariant_compact_prose(self) -> None:
        trimmed = (
            "The marsh had no patience for heroes, only for feet that kept moving."
            "Did the courier know?Of course not—but doubt never stopped them."
            'When the lantern died, they shouted "Run!!!"and vanished into the reeds.'
        )
        self.assertLessEqual(len(trimmed), TTS_CHUNK_MAX_CHARS)
        _assert_joined_raw_matches_trimmed(trimmed)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        self.assertEqual(len(chunks), 1)
        r0 = chunks[0].raw_line
        self.assertIn("?", r0)
        self.assertIn("!", r0)

    def test_interrobang_run_single_boundary(self) -> None:
        trimmed = "x" * 100 + "Really?!" + "y" * 100 + "." + "z" * 200
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        _assert_joined_raw_matches_trimmed(trimmed)
        self.assertGreaterEqual(len(chunks), 2)
        inter = next(c for c in chunks if "?" in c.raw_line)
        self.assertIn("?!", inter.raw_line)

    def test_comma_only_clause_no_split(self) -> None:
        trimmed = ("xyzzy," * 60).rstrip(",")
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].raw_line, trimmed)

    def test_questions_split_like_periods_when_long(self) -> None:
        a, b = "q" * 180, "r" * 180
        trimmed = a + "?" + b
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].raw_line.endswith("?"))
        _assert_joined_raw_matches_trimmed(trimmed)

    def test_wrapping_tag_span_repairs_speak_text_across_chunks(self) -> None:
        trimmed = (
            "a" * 120
            + "."
            + "<whisper>"
            + ("b" * 220)
            + "."
            + ("c" * 40)
            + "</whisper>"
            + ("d" * 120)
            + "."
        )
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        _assert_joined_raw_matches_trimmed(trimmed)
        open_chunk = next(c for c in chunks if "<whisper>" in c.raw_line)
        close_chunk = next(c for c in chunks if "</whisper>" in c.raw_line)
        self.assertIsNot(open_chunk, close_chunk)
        self.assertNotIn("</whisper>", open_chunk.raw_line)
        self.assertNotIn("<whisper>", close_chunk.raw_line)
        self.assertTrue(close_chunk.speak_text.startswith("<whisper>"))
        self.assertNotIn("</whisper>", open_chunk.speak_text)

    def test_nested_wrapping_tags_reopen_in_stack_order(self) -> None:
        trimmed = (
            "a" * 120
            + "."
            + "<slow><soft>"
            + ("b" * 220)
            + "."
            + ("c" * 40)
            + "</soft></slow>"
            + ("d" * 120)
            + "."
        )
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        _assert_joined_raw_matches_trimmed(trimmed)
        open_chunk = next(c for c in chunks if "<slow><soft>" in c.raw_line)
        close_chunk = next(c for c in chunks if "</soft></slow>" in c.raw_line)
        self.assertIsNot(open_chunk, close_chunk)
        self.assertTrue(close_chunk.speak_text.startswith("<slow><soft>"))
        self.assertNotIn("</soft></slow>", open_chunk.speak_text)

    def test_whitespace_tag_name_repairs_across_chunks(self) -> None:
        trimmed = (
            "a" * 120
            + "."
            + "<soft whisper>"
            + ("b" * 220)
            + "."
            + ("c" * 40)
            + "</soft whisper>"
            + ("d" * 120)
            + "."
        )
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        _assert_joined_raw_matches_trimmed(trimmed)
        open_chunk = next(c for c in chunks if "<soft whisper>" in c.raw_line)
        close_chunk = next(c for c in chunks if "</soft whisper>" in c.raw_line)
        self.assertIsNot(open_chunk, close_chunk)
        self.assertTrue(close_chunk.speak_text.startswith("<soft whisper>"))
        self.assertNotIn("</soft whisper>", open_chunk.speak_text)

    def test_unclosed_nested_tags_still_chunk_and_repair(self) -> None:
        trimmed = (
            "> [Amy] <soft><build-intensity>"
            + ("P" * 180)
            + "."
            + ("Q" * 180)
            + "."
            + ("R" * 80)
        )
        self.assertGreater(len(trimmed), TTS_CHUNK_MAX_CHARS)
        chunks = tts_chunks_for_eligible_trimmed_line(trimmed, 1)
        _assert_joined_raw_matches_trimmed(trimmed)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].speak_text.startswith("<soft><build-intensity>"))
        self.assertTrue(chunks[1].speak_text.startswith("<soft><build-intensity>"))
        self.assertNotIn("</build-intensity>", chunks[0].speak_text)
        self.assertNotIn("</build-intensity>", chunks[1].speak_text)
        self.assertNotIn("</soft>", chunks[0].speak_text)
        self.assertNotIn("</soft>", chunks[1].speak_text)


class TestTtsMountPrefix(unittest.TestCase):
    def test_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nar = Path(tmp) / "narrative" / "camp"
            nar.mkdir(parents=True)
            node = NarrativeNode(narrative_root=nar, key_path=("chapter", "scene"))
            self.assertEqual(
                tts_cache_mount_prefix(node),
                "tts-cache/camp/chapter/scene",
            )


if __name__ == "__main__":
    unittest.main()
