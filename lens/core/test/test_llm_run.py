"""Unit tests for the LlmRun envelope."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from lens.core.context import CrawlResult
from lens.core.generation_artifacts import (
    GenerationArtifacts,
    GenerationSegment,
    compose_for_operator,
)
from lens.core.llm import FinalPayload, ToolCall, final_payload_from_text
from lens.core.llm_run import LlmRunRequest, run_llm, run_llm_final


class TestRunLlm(unittest.IsolatedAsyncioTestCase):
    async def test_prebuilt_messages_delegates_to_generate(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        captured: dict[str, Any] = {}

        async def fake_generate(*args: Any, **kwargs: Any) -> GenerationArtifacts:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return GenerationArtifacts(
                segments=[GenerationSegment("prose", "output")]
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=messages,
                llm_id="test-llm",
                operator_name="write",
                reasoning="low",
            )
            result = await run_llm(request, generate=fake_generate)

        self.assertIn("output", compose_for_operator(result, "write"))
        self.assertEqual(captured["args"], (messages, root))
        self.assertEqual(captured["kwargs"]["llm_id"], "test-llm")
        self.assertEqual(captured["kwargs"]["operator_name"], "write")
        self.assertEqual(captured["kwargs"]["reasoning"], "low")
        self.assertEqual(captured["kwargs"]["interrupt_policy"], "return_empty")

    async def test_builds_messages_from_operator_context(self) -> None:
        captured_messages: list[dict[str, str]] = []
        crawl_result = MagicMock(spec=CrawlResult)
        crawl_result.modality_resolution = None
        crawl_result.modality_context = None
        operator = MagicMock()
        operator.build_messages.return_value = [{"role": "user", "content": "from build"}]

        async def fake_generate(
            messages: list[dict[str, str]], *args: Any, **kwargs: Any
        ) -> GenerationArtifacts:
            captured_messages.extend(messages)
            return GenerationArtifacts(segments=[GenerationSegment("prose", "built")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                crawl_result=crawl_result,
                operator=operator,
                params={"prompt": "go"},
            )
            result = await run_llm(request, generate=fake_generate)

        self.assertIn("built", compose_for_operator(result, "write"))
        operator.build_messages.assert_called_once_with(
            crawl_result,
            {"prompt": "go"},
            session=None,
            narrative=None,
            resolved_modalities=None,
        )
        self.assertEqual(captured_messages, [{"role": "user", "content": "from build"}])

    async def test_missing_messages_and_context_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(project_root=root)
            with self.assertRaises(ValueError):
                await run_llm(request, generate=MagicMock())

    async def test_forwards_stream_callbacks(self) -> None:
        seen: list[str] = []

        async def on_token(chunk: str) -> None:
            seen.append(chunk)

        async def fake_generate(*args: Any, **kwargs: Any) -> GenerationArtifacts:
            cb = kwargs.get("on_preview")
            if cb is not None:
                await cb("tok")
            return GenerationArtifacts(segments=[GenerationSegment("prose", "done")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "x"}],
                on_token=on_token,
            )
            result = await run_llm(request, generate=fake_generate)

        self.assertIn("done", compose_for_operator(result, "write"))
        self.assertEqual(seen, ["tok"])

    async def test_messages_append_after_build(self) -> None:
        captured_messages: list[dict[str, str]] = []
        crawl_result = MagicMock(spec=CrawlResult)
        operator = MagicMock()
        operator.build_messages.return_value = [{"role": "user", "content": "base"}]
        feedback = (
            {"role": "assistant", "content": "prior"},
            {"role": "user", "content": "retry"},
        )

        async def fake_generate(
            messages: list[dict[str, str]], *args: Any, **kwargs: Any
        ) -> GenerationArtifacts:
            captured_messages.extend(messages)
            return GenerationArtifacts(segments=[GenerationSegment("prose", "ok")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                crawl_result=crawl_result,
                operator=operator,
                params={"prompt": "go"},
                messages_append=feedback,
            )
            await run_llm(request, generate=fake_generate)

        self.assertEqual(
            captured_messages,
            [
                {"role": "user", "content": "base"},
                {"role": "assistant", "content": "prior"},
                {"role": "user", "content": "retry"},
            ],
        )

    async def test_forwards_extended_kwargs(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_generate(*args: Any, **kwargs: Any) -> GenerationArtifacts:
            captured["kwargs"] = kwargs
            return GenerationArtifacts(segments=[GenerationSegment("prose", "ok")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "x"}],
                enable_thinking=True,
                max_command_tool_iterations=6,
                stop_sequences=["[/write]: #"],
            )
            await run_llm(request, generate=fake_generate)

        self.assertTrue(captured["kwargs"]["enable_thinking"])
        self.assertEqual(captured["kwargs"]["max_command_tool_iterations"], 6)
        self.assertEqual(captured["kwargs"]["stop_sequences"], ["[/write]: #"])


class TestRunLlmFinal(unittest.IsolatedAsyncioTestCase):
    async def test_returns_full_payload_with_tool_calls(self) -> None:
        payload = final_payload_from_text(
            "",
            tool_calls=[
                ToolCall(id="t1", name="compress_collate", arguments={"id": "x"})
            ],
        )

        async def fake_collect(*args: Any, **kwargs: Any) -> FinalPayload:
            cb = kwargs.get("on_preview")
            if cb is not None:
                await cb("preview")
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "pick a range"}],
                operator_name="compress",
            )
            with patch(
                "lens.core.llm_run.stream_final_payload",
                side_effect=fake_collect,
            ):
                result = await run_llm_final(request)

        self.assertEqual(result.tool_calls[0].name, "compress_collate")
        self.assertEqual(result.text, "")

    async def test_raises_when_stream_has_no_final(self) -> None:
        from lens.core.llm import LLMError

        async def fake_collect(*args: Any, **kwargs: Any) -> FinalPayload:
            raise LLMError("LLM stream ended without a completion event")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "x"}],
            )
            with patch(
                "lens.core.llm_run.stream_final_payload",
                side_effect=fake_collect,
            ):
                with self.assertRaises(LLMError):
                    await run_llm_final(request)

    async def test_raise_policy_on_interrupt(self) -> None:
        from lens.core.llm import LLMError

        payload = final_payload_from_text("partial", interrupted=True)

        async def fake_collect(*args: Any, **kwargs: Any) -> FinalPayload:
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "x"}],
                interrupt_policy="raise",
            )
            with patch(
                "lens.core.llm_run.stream_final_payload",
                side_effect=fake_collect,
            ):
                with self.assertRaises(LLMError) as ctx:
                    await run_llm_final(request)
        self.assertIn("interrupted", str(ctx.exception).lower())

    async def test_return_empty_policy_preserves_interrupted_payload(self) -> None:
        payload = final_payload_from_text("partial", interrupted=True)

        async def fake_collect(*args: Any, **kwargs: Any) -> FinalPayload:
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LlmRunRequest(
                project_root=root,
                messages=[{"role": "user", "content": "x"}],
            )
            with patch(
                "lens.core.llm_run.stream_final_payload",
                side_effect=fake_collect,
            ):
                result = await run_llm_final(request)

        self.assertTrue(result.interrupted)
        self.assertEqual(result.text, "partial")


if __name__ == "__main__":
    unittest.main()
