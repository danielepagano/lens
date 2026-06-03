"""Unit tests for generation artifact composition."""

from __future__ import annotations

import unittest

from lens.core.generation_artifacts import (
    ComposePolicy,
    GenerationArtifacts,
    GenerationSegment,
    StreamComposePolicy,
    compose_for_operator,
    compose_for_stream,
    compose_generation_artifacts,
    compose_tool_call_for_stream,
    format_tool_event_for_log,
    get_stream_compose_policy,
    register_stream_compose_policy,
)


class TestComposeGenerationArtifacts(unittest.TestCase):
    def test_narrative_interleaves_segments(self) -> None:
        fence = "```tool-call\nCalled Tool 'kb_get' (10 bytes)\n{}\n```\n"
        artifacts = GenerationArtifacts(
            segments=[
                GenerationSegment("prose", "Before."),
                GenerationSegment("tool_call", fence),
                GenerationSegment("prose", " After."),
            ]
        )
        out = compose_generation_artifacts(artifacts, ComposePolicy.NARRATIVE)
        self.assertIn("Before.", out)
        self.assertIn("```tool-call", out)
        self.assertIn("After.", out)

    def test_audit_comment_wraps_stray_prose(self) -> None:
        fence = "```tool-call\nCalled Tool 'kb_patch' (zero bytes)\n{}\n```\n"
        artifacts = GenerationArtifacts(
            segments=[
                GenerationSegment("prose", "Before."),
                GenerationSegment("tool_call", fence),
                GenerationSegment("prose", "stray note"),
            ]
        )
        out = compose_generation_artifacts(
            artifacts, ComposePolicy.AUDIT_COMMENT, audit_comment_tag="remember"
        )
        self.assertIn(fence.strip(), out)
        self.assertIn("<!-- remember:", out)
        self.assertIn("stray note", out)
        self.assertIn("stray note", out)

    def test_write_narrative_keeps_interview_prose_beside_tools(self) -> None:
        fence = "```tool-call\nCalled Tool 'kb_get' (0 bytes)\n{}\n```\n"
        artifacts = GenerationArtifacts(
            segments=[
                GenerationSegment("prose", "What is your character's name?"),
                GenerationSegment("tool_call", fence),
            ]
        )
        out = compose_for_operator(artifacts, "design")
        self.assertIn("What is your character's name?", out)
        self.assertIn("```tool-call", out)
        self.assertNotIn("<!-- tool-audit:", out)

    def test_remember_prose_only_is_wrapped(self) -> None:
        artifacts = GenerationArtifacts(
            segments=[GenerationSegment("prose", "only prose")]
        )
        out = compose_for_operator(artifacts, "remember")
        self.assertIn("<!-- remember:", out)
        self.assertIn("only prose", out)


# ---------------------------------------------------------------------------
# Stream composer tests
# ---------------------------------------------------------------------------


class TestStreamComposePolicy(unittest.TestCase):
    def test_default_interleave(self) -> None:
        self.assertEqual(
            get_stream_compose_policy("write"), StreamComposePolicy.INTERLEAVE,
        )
        self.assertEqual(
            get_stream_compose_policy("play"), StreamComposePolicy.INTERLEAVE,
        )

    def test_design_structured(self) -> None:
        self.assertEqual(
            get_stream_compose_policy("design"), StreamComposePolicy.STRUCTURED,
        )

    def test_remember_default_prose_only(self) -> None:
        self.assertEqual(
            get_stream_compose_policy("remember"), StreamComposePolicy.PROSE_ONLY,
        )

    def test_unknown_operator_defaults_interleave(self) -> None:
        self.assertEqual(
            get_stream_compose_policy("nonexistent"), StreamComposePolicy.INTERLEAVE,
        )

    def test_custom_registration(self) -> None:
        register_stream_compose_policy("test_op", StreamComposePolicy.STRUCTURED)
        self.assertEqual(
            get_stream_compose_policy("test_op"), StreamComposePolicy.STRUCTURED,
        )


class TestComposeForStream(unittest.TestCase):
    def setUp(self) -> None:
        self.prose_seg = GenerationSegment("prose", "Hello world.")
        self.tool_fence = (
            "```tool-call\nCalled Tool 'kb_get' (42 bytes)\n{}\n```\n"
        )
        self.tool_seg = GenerationSegment("tool_call", self.tool_fence)

    def test_interleave_yields_preview_for_all(self) -> None:
        artifacts = GenerationArtifacts(segments=[self.prose_seg, self.tool_seg])
        chunks = compose_for_stream(artifacts, "write")
        self.assertEqual(len(chunks), 2)
        kind0, content0 = chunks[0]
        kind1, content1 = chunks[1]
        self.assertEqual(kind0, "preview")
        self.assertEqual(content0, "Hello world.")
        self.assertEqual(kind1, "preview")
        self.assertIn("kb_get", str(content1))

    def test_prose_only_skips_tool_calls(self) -> None:
        artifacts = GenerationArtifacts(segments=[self.prose_seg, self.tool_seg])
        chunks = compose_for_stream(artifacts, "remember")
        self.assertEqual(len(chunks), 1)
        kind, content = chunks[0]
        self.assertEqual(kind, "preview")
        self.assertEqual(content, "Hello world.")

    def test_prose_only_empty_with_only_tool(self) -> None:
        artifacts = GenerationArtifacts(segments=[self.tool_seg])
        chunks = compose_for_stream(artifacts, "remember")
        self.assertEqual(len(chunks), 0)

    def test_structured_yields_tool_event_for_tool_call(self) -> None:
        register_stream_compose_policy("test_s_structured", StreamComposePolicy.STRUCTURED)
        artifacts = GenerationArtifacts(segments=[self.prose_seg, self.tool_seg])
        chunks = compose_for_stream(artifacts, "test_s_structured")
        self.assertEqual(len(chunks), 2)
        kind0, content0 = chunks[0]
        kind1, content1 = chunks[1]
        self.assertEqual(kind0, "preview")
        self.assertEqual(content0, "Hello world.")
        self.assertEqual(kind1, "tool_event")
        self.assertIsInstance(content1, dict)
        if isinstance(content1, dict):
            self.assertIn("fence_text", content1)

    def test_structured_tool_event_dict(self) -> None:
        register_stream_compose_policy("test_t_structured", StreamComposePolicy.STRUCTURED)
        kind, content = compose_tool_call_for_stream(
            "kb_patch", {"id": "test", "patches": [{"start": {"target": "foo"}}]},
            response_char_len=123,
            operator_name="test_t_structured",
        )
        self.assertEqual(kind, "tool_event")
        self.assertIsInstance(content, dict)
        if isinstance(content, dict):
            self.assertEqual(content["name"], "kb_patch")
            self.assertIn("response=123B", content["summary"])
            self.assertIn("```tool-call", content["fence_text"])

    def test_interleave_via_compose_tool_call(self) -> None:
        kind, content = compose_tool_call_for_stream(
            "kb_get", {"id": "person.frodo"},
            response_char_len=42,
            operator_name="write",
        )
        self.assertEqual(kind, "preview")
        self.assertIsInstance(content, str)
        if isinstance(content, str):
            self.assertIn("```tool-call", content)
            self.assertIn("kb_get", content)

    def test_prose_only_via_compose_tool_call(self) -> None:
        kind, content = compose_tool_call_for_stream(
            "kb_get", {"id": "person.frodo"},
            response_char_len=42,
            operator_name="remember",
        )
        self.assertEqual(kind, "skip")
        self.assertIsNone(content)

    def test_interleave_encode_fence(self) -> None:
        def _encode(s: str) -> str:
            return s.upper()
        kind, content = compose_tool_call_for_stream(
            "kb_get", {"id": "test"},
            response_char_len=10,
            operator_name="advance",
            encode_fence=_encode,
        )
        self.assertEqual(kind, "preview")
        self.assertIsInstance(content, str)
        if isinstance(content, str):
            self.assertTrue(content.isupper() or content.startswith("```TOOL-CALL"))


class TestFormatToolEventForLog(unittest.TestCase):
    def test_compact_summary_includes_name_and_args(self) -> None:
        out = format_tool_event_for_log(
            "kb_patch", {"id": "obj", "patches": []},
            response_char_len=512,
        )
        self.assertIn("Tool 'kb_patch'", out)
        self.assertIn("args=[id, patches]", out)
        self.assertIn("response=512B", out)

    def test_no_args_omits_arg_keys(self) -> None:
        out = format_tool_event_for_log(
            "kb_get", {},
            response_char_len=None,
        )
        self.assertIn("Tool 'kb_get'", out)
        self.assertNotIn("args=", out)

    def test_no_response_size(self) -> None:
        out = format_tool_event_for_log(
            "kb_get", {"id": "x"},
            response_char_len=None,
        )
        self.assertIn("Tool 'kb_get'", out)
        self.assertNotIn("response", out)


class TestComposeForStreamPreservesPersist(unittest.TestCase):
    def test_artifacts_unchanged(self) -> None:
        fence = "```tool-call\nCalled Tool 'kb_get' (0 bytes)\n{}\n```\n"
        artifacts = GenerationArtifacts(
            segments=[
                GenerationSegment("prose", "Hello"),
                GenerationSegment("tool_call", fence),
            ]
        )
        persist_before = compose_for_operator(artifacts, "design")
        _chunks = compose_for_stream(artifacts, "design")
        persist_after = compose_for_operator(artifacts, "design")
        self.assertEqual(persist_before, persist_after)
        self.assertIn("Hello", persist_after)
        self.assertIn("```tool-call", persist_after)


if __name__ == "__main__":
    unittest.main()
