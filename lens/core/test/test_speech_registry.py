"""Tests for the speech backend registry."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.speech.api.xai import XaiSpeechBackend
from lens.core.speech.api.openrouter import OpenRouterSpeechBackend
from lens.core.speech import registry as speech_registry
from lens.core.speech.backend import SpeechError


def _write_lens_toml(root: Path, body: str) -> None:
    (root / "lens.toml").write_text(body)


class LoadDescriptorTests(unittest.TestCase):
    def test_no_speech_blocks_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(root, '[project]\nnarrative = "x"\n')
            with self.assertRaises(SpeechError):
                speech_registry.load_descriptor(root)

    def test_first_block_is_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_KEY"
""",
            )
            descriptor = speech_registry.load_descriptor(root)
            self.assertEqual(descriptor.id, "[default]")
            self.assertEqual(descriptor.api, "xai")
            self.assertEqual(descriptor.max_text_chars, 15000)
            same = speech_registry.load_descriptor(root, "[default]")
            self.assertEqual(same.api, descriptor.api)

    def test_pick_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_KEY"

[[speech]]
id = "alt"
api = "xai"
api_key_env = "FAKE_KEY"
max_text_chars = 1000
timeout_seconds = 60
""",
            )
            descriptor = speech_registry.load_descriptor(root, "alt")
            self.assertEqual(descriptor.id, "alt")
            self.assertEqual(descriptor.max_text_chars, 1000)
            self.assertEqual(descriptor.timeout_seconds, 60.0)

    def test_refine_llm_id_in_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_KEY"
grammar = "xai"
refine_llm_id = "fast"
""",
            )
            descriptor = speech_registry.load_descriptor(root)
            self.assertEqual(descriptor.refine_llm_id, "fast")

    def test_default_voice_in_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_KEY"
default_voice = "rex"
""",
            )
            descriptor = speech_registry.load_descriptor(root)
            self.assertEqual(descriptor.default_voice, "rex")

    def test_unknown_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
id = "only"
api = "xai"
api_key_env = "FAKE_KEY"
""",
            )
            with self.assertRaises(SpeechError):
                speech_registry.load_descriptor(root, "nope")


class ResolveBackendTests(unittest.TestCase):
    def test_resolve_xai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_SPEECH_KEY"
""",
            )
            with mock.patch.dict(os.environ, {"FAKE_SPEECH_KEY": "xai_test_key"}):
                descriptor, backend = speech_registry.resolve(root)
            self.assertEqual(descriptor.api, "xai")
            self.assertIsInstance(backend, XaiSpeechBackend)

    def test_resolve_openrouter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "openrouter"
api_key_env = "FAKE_SPEECH_KEY"
model = "openai/gpt-4o-mini-tts-2025-12-15"
""",
            )
            with mock.patch.dict(os.environ, {"FAKE_SPEECH_KEY": "k"}):
                descriptor, backend = speech_registry.resolve(root)
            self.assertEqual(descriptor.api, "openrouter")
            self.assertIsInstance(backend, OpenRouterSpeechBackend)

    def test_resolve_missing_api_key_env_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "DEFINITELY_MISSING_SPEECH_VAR"
""",
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DEFINITELY_MISSING_SPEECH_VAR", None)
                with self.assertRaises(SpeechError):
                    speech_registry.resolve(root)

    def test_unknown_grammar_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "xai"
api_key_env = "FAKE_SPEECH_KEY"
grammar = "not-a-grammar"
""",
            )
            with self.assertRaises(SpeechError) as ctx:
                speech_registry.load_descriptor(root)
            self.assertIn("grammar", str(ctx.exception).lower())

    def test_unknown_api_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_lens_toml(
                root,
                """
[project]
narrative = "x"

[[speech]]
api = "future-tts"
api_key_env = "FAKE_SPEECH_KEY"
""",
            )
            with mock.patch.dict(os.environ, {"FAKE_SPEECH_KEY": "k"}):
                with self.assertRaises(SpeechError):
                    speech_registry.resolve(root)


if __name__ == "__main__":
    unittest.main()
