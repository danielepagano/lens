"""Speech markup gates and context cache (no TTS API key required)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lens.core.modalities import resolve_modalities
from lens.core.modalities.apply import (
    attach_modality_resolution_to_crawl,
    prepare_modality_context,
)
from lens.core.modalities.catalog.speech_markup import SpeechMarkupModality
from lens.core.modalities.types import ModalityContext
from lens.core.narrative import NarrativeNode
from lens.core.operators.write import WriteOperator
from lens.core.pinning import set_modality_config
from lens.core.speech.spec import SpeechDescriptor
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp


def _make_project(tmp: Path) -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(
        """
[project]
narrative = "test"

[[speech]]
api = "xai"
api_key_env = "MISSING_SPEECH_KEY"
grammar = "xai"
""",
        encoding="utf-8",
    )
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n", encoding="utf-8")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


class TestSpeechMarkupGates(unittest.TestCase):
    def test_active_without_api_key_when_grammar_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality_config(narrative, "speech_markup", "enabled", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("speech_markup", resolved.active_ids)

    def test_active_when_grammar_omitted_but_api_matches_a_grammar_id(self) -> None:
        """api = "xai" with no explicit grammar= still gates active, since
        grammar defaults to api when they name the same registered grammar."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "lens.toml").write_text(
                """
[project]
narrative = "test"

[[speech]]
api = "xai"
api_key_env = "MISSING_SPEECH_KEY"
""",
                encoding="utf-8",
            )
            narrative_dir = root / "narrative" / "test"
            narrative_dir.mkdir(parents=True)
            (narrative_dir / "_node.md").write_text("# test\n", encoding="utf-8")
            (root / "knowledge").mkdir(exist_ok=True)
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "project"], cwd=root, capture_output=True, check=True
            )
            narrative = NarrativeNode(narrative_root=narrative_dir, key_path=())
            set_modality_config(narrative, "speech_markup", "enabled", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("speech_markup", resolved.active_ids)

    def test_prepare_context_reuses_cache(self) -> None:
        descriptor = SpeechDescriptor(
            id="[default]",
            api="xai",
            model="",
            grammar="xai",
            max_text_chars=15000,
            timeout_seconds=120.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            ctx = ModalityContext(
                session=None,
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            set_modality_config(narrative, "speech_markup", "enabled", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("speech_markup", resolved.active_ids)
            with patch(
                "lens.core.modalities.catalog.speech_markup.speech_registry.load_descriptor",
                return_value=descriptor,
            ) as load_mock:
                ctx = prepare_modality_context(ctx, resolved)
                self.assertEqual(load_mock.call_count, 1)
                self.assertIsNotNone(ctx.speech_markup)
                mod = SpeechMarkupModality()
                mod.prompt_addenda(ctx)
                mod.gates(ctx)
                self.assertEqual(load_mock.call_count, 1)

    def test_attach_to_crawl_primes_cache(self) -> None:
        from lens.core.context import CrawlGraph, CrawlResult

        descriptor = SpeechDescriptor(
            id="[default]",
            api="xai",
            model="",
            grammar="xai",
            max_text_chars=15000,
            timeout_seconds=120.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality_config(narrative, "speech_markup", "enabled", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("speech_markup", resolved.active_ids)
            ctx = ModalityContext(
                session=None,
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            crawl = CrawlResult(CrawlGraph(), project_root=root, current_node=narrative)
            with patch(
                "lens.core.modalities.catalog.speech_markup.speech_registry.load_descriptor",
                return_value=descriptor,
            ) as load_mock:
                attach_modality_resolution_to_crawl(crawl, resolved=resolved, ctx=ctx)
                assert crawl.modality_context is not None
                self.assertIsNotNone(crawl.modality_context.speech_markup)
                SpeechMarkupModality().prompt_addenda(crawl.modality_context)
                self.assertEqual(load_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
