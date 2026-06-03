"""Tests for isolated modality workflow_refine LLM calls."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.modalities.types import RefinePassSpec
from lens.core.modalities.workflow import run_refine_pass
from lens.core.project import ProjectSession


def _init_repo(tmp: Path) -> Path:
    (tmp / "lens.toml").write_text(
        '[[llm]]\nid = "mock"\nmodel = "mock"\nbase_url = "http://127.0.0.1:9"\n'
        'api_key_env = "MISSING"\n',
        encoding="utf-8",
    )
    (tmp / "narrative").mkdir()
    (tmp / "knowledge").mkdir()
    return tmp


class TestRunRefinePass(unittest.TestCase):
    def test_sends_only_instruction_no_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            session = ProjectSession(root, root)
            captured: list[list[dict[str, str]]] = []

            async def fake_run_llm(request: object) -> GenerationArtifacts:
                from lens.core.llm_run import LlmRunRequest

                assert isinstance(request, LlmRunRequest)
                assert request.messages is not None
                captured.append(
                    [{"role": m["role"], "content": m["content"]} for m in request.messages]
                )
                return GenerationArtifacts(
                    segments=[GenerationSegment("prose", '{"lines":["ok"]}')]
                )

            spec = RefinePassSpec(instruction="refine-only prompt body")

            async def run() -> None:
                with patch(
                    "lens.core.modalities.workflow.run_llm",
                    side_effect=fake_run_llm,
                ):
                    await run_refine_pass(
                        session,
                        spec,
                        operator_name="write",
                    )

            asyncio.run(run())

            self.assertEqual(len(captured), 1)
            messages = captured[0]
            self.assertEqual(
                messages,
                [{"role": "user", "content": "refine-only prompt body"}],
            )
            joined = " ".join(m["content"] for m in messages)
            self.assertNotIn("[RELEVANT KNOWLEDGE]", joined)
            self.assertNotIn("[CURRENT PASSAGE]", joined)

    def test_includes_system_message_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            session = ProjectSession(root, root)
            captured: list[list[dict[str, str]]] = []

            async def fake_run_llm(request: object) -> GenerationArtifacts:
                from lens.core.llm_run import LlmRunRequest

                assert isinstance(request, LlmRunRequest)
                assert request.messages is not None
                captured.append(
                    [{"role": m["role"], "content": m["content"]} for m in request.messages]
                )
                return GenerationArtifacts(
                    segments=[GenerationSegment("prose", '{"lines":[]}')]
                )

            spec = RefinePassSpec(
                instruction="user body",
                system_message="JSON only",
            )

            async def run() -> None:
                with patch(
                    "lens.core.modalities.workflow.run_llm",
                    side_effect=fake_run_llm,
                ):
                    await run_refine_pass(session, spec, operator_name="write")

            asyncio.run(run())
            self.assertEqual(
                captured[0],
                [
                    {"role": "system", "content": "JSON only"},
                    {"role": "user", "content": "user body"},
                ],
            )


if __name__ == "__main__":
    unittest.main()
