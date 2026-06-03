"""Tests for speech markup line selection and refine merge."""

from __future__ import annotations

import json
import logging
import unittest

from lens.core.modalities.catalog.speech_markup import (
    apply_refined_speech_markup,
    apply_refined_speech_markup_from_model_output,
    encode_refine_lines_json,
    parse_refine_lines_json,
    select_speech_markup_line_refs,
    split_lines_keepends,
)
from lens.core.speech.grammars import (
    clear_tts_grammar_registry_for_tests,
    ensure_builtin_tts_grammars_registered,
    get_tts_grammar,
)


class TestSpeechMarkupRefineJson(unittest.TestCase):
    def test_encode_and_parse_roundtrip(self) -> None:
        payload = encode_refine_lines_json(["a", "b"])
        parsed = parse_refine_lines_json(payload)
        self.assertEqual(parsed, ["a", "b"])

    def test_nasty_dialogue_roundtrip(self) -> None:
        bodies = [
            'He said "hello" and \\escaped',
            "Line two\nstill one string",
        ]
        payload = encode_refine_lines_json(bodies)
        parsed = parse_refine_lines_json(payload)
        self.assertEqual(parsed, bodies)

    def test_parse_strips_markdown_fence(self) -> None:
        inner = json.dumps({"lines": ["x"]})
        raw = f"```json\n{inner}\n```"
        self.assertEqual(parse_refine_lines_json(raw), ["x"])

    def test_parse_finds_json_after_preamble(self) -> None:
        inner = json.dumps({"lines": ["ok"]})
        raw = f"Here is the result:\n{inner}"
        self.assertEqual(parse_refine_lines_json(raw), ["ok"])

    def test_parse_invalid_returns_none(self) -> None:
        self.assertIsNone(parse_refine_lines_json("not json"))
        self.assertIsNone(parse_refine_lines_json('{"items": []}'))


class TestSpeechMarkupRefine(unittest.TestCase):
    def setUp(self) -> None:
        clear_tts_grammar_registry_for_tests()
        ensure_builtin_tts_grammars_registered()

    def tearDown(self) -> None:
        clear_tts_grammar_registry_for_tests()

    def test_select_attributed_and_tagged_lines(self) -> None:
        lines = [
            "Narration stays out.",
            "> [Riley] Hello [laugh] there.",
            "Also [whispers] a tagged plain line.",
            "",
        ]
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0].index, 1)
        self.assertEqual(refs[0].prefix, "> [Riley] ")
        self.assertEqual(refs[0].body, "Hello [laugh] there.")
        self.assertEqual(refs[1].index, 2)
        self.assertEqual(refs[1].prefix, "")
        self.assertEqual(refs[1].body, "Also [whispers] a tagged plain line.")

    def test_apply_refined_restores_attribution_prefix(self) -> None:
        text = "Before.\n> [Riley] old line.\nAfter.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        merged = apply_refined_speech_markup(
            lines,
            refs,
            ["new [breath] line."],
            has_trailing_newline=trailing,
        )
        self.assertEqual(merged, "Before.\n> [Riley] new [breath] line.\nAfter.\n")

    def test_apply_from_json_model_output(self) -> None:
        text = "Before.\n> [Riley] old.\nAfter.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        model_out = json.dumps({"lines": ["new [breath] line."]})
        result = apply_refined_speech_markup_from_model_output(
            lines,
            refs,
            model_out,
            has_trailing_newline=trailing,
        )
        self.assertTrue(result.applied)
        self.assertEqual(
            result.text, "Before.\n> [Riley] new [breath] line.\nAfter.\n"
        )

    def test_apply_refined_mismatch_returns_original(self) -> None:
        text = "> [A] one.\n> [B] two.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        merged = apply_refined_speech_markup(
            lines,
            refs,
            ["only one line"],
            has_trailing_newline=trailing,
        )
        self.assertEqual(merged, text)

    def test_apply_from_json_failure_logs_warning(self) -> None:
        text = "> [A] one.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        with self.assertLogs(
            "lens.core.modalities.catalog.speech_markup", level=logging.WARNING
        ) as logs:
            result = apply_refined_speech_markup_from_model_output(
                lines,
                refs,
                "Sorry, here you go: not json",
                has_trailing_newline=trailing,
            )
        self.assertEqual(result.text, text)
        self.assertFalse(result.applied)
        self.assertTrue(result.warnings)
        self.assertTrue(any("parse JSON" in w for w in result.warnings))
        self.assertTrue(any("speech refine" in r.message for r in logs.records))

    def test_apply_from_json_identity_no_warning(self) -> None:
        text = "> [X] same body.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        model_out = json.dumps({"lines": [refs[0].body]})
        result = apply_refined_speech_markup_from_model_output(
            lines,
            refs,
            model_out,
            has_trailing_newline=trailing,
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.warnings, ())
        self.assertEqual(result.text, text)

    def test_apply_from_json_line_count_mismatch_message(self) -> None:
        text = "> [A] one.\n> [B] two.\n"
        lines, trailing = split_lines_keepends(text)
        xai = get_tts_grammar("xai")
        assert xai is not None
        refs = select_speech_markup_line_refs(lines, xai.tag_detect)
        model_out = json.dumps({"lines": ["only"]})
        with self.assertLogs(
            "lens.core.modalities.catalog.speech_markup", level=logging.WARNING
        ):
            result = apply_refined_speech_markup_from_model_output(
                lines,
                refs,
                model_out,
                has_trailing_newline=trailing,
            )
        self.assertFalse(result.applied)
        self.assertEqual(result.text, text)
        self.assertTrue(result.warnings)
        self.assertIn("line count mismatch", result.warnings[0])
        self.assertIn("1", result.warnings[0])
        self.assertIn("2", result.warnings[0])

    def test_gemini_tag_detect_brackets(self) -> None:
        gemini = get_tts_grammar("gemini")
        assert gemini is not None
        self.assertTrue(gemini.tag_detect.search("Line with [gasp] in the middle."))
        self.assertFalse(gemini.tag_detect.search("No tags here."))

    def test_xai_tag_detect_angle_and_square(self) -> None:
        xai = get_tts_grammar("xai")
        assert xai is not None
        self.assertTrue(xai.tag_detect.search("> [x] <soft>hi</soft>"))
        self.assertTrue(xai.tag_detect.search("plain [pause] ok"))


if __name__ == "__main__":
    unittest.main()
