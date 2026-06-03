"""Tests for Fly deploy secret collection (LLM + image + speech api_key_env)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.commands.deploy import (
    collect_all_project_api_key_secrets,
    collect_api_key_secrets_for_lens_config,
)
from lens.core.exceptions import LensException


class DeployApiKeySecretsTests(unittest.TestCase):
    def test_image_block_collected(self) -> None:
        config = {
            "image": [{"api_key_env": "A2E_TOKEN", "api": "a2e", "model": "a2e"}]
        }
        with mock.patch.dict(os.environ, {"A2E_TOKEN": "sk_test"}):
            got = collect_api_key_secrets_for_lens_config(config)
        self.assertEqual(got, {"A2E_TOKEN": "sk_test"})

    def test_llm_and_image_same_env_deduped(self) -> None:
        config = {
            "llm": [{"api_key_env": "SHARED"}],
            "image": [{"api_key_env": "SHARED"}],
        }
        with mock.patch.dict(os.environ, {"SHARED": "one"}):
            out = collect_api_key_secrets_for_lens_config(config)
        self.assertEqual(out, {"SHARED": "one"})

    def test_speech_block_collected(self) -> None:
        config = {
            "speech": [{"api_key_env": "XAI_API_KEY", "api": "xai"}],
        }
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "xai_secret"}):
            got = collect_api_key_secrets_for_lens_config(config)
        self.assertEqual(got, {"XAI_API_KEY": "xai_secret"})

    def test_missing_speech_key_raises(self) -> None:
        config = {"speech": [{"api_key_env": "MISSING_SPEECH"}]}
        with mock.patch.dict(os.environ, {"MISSING_SPEECH": ""}):
            with self.assertRaises(LensException) as ctx:
                collect_api_key_secrets_for_lens_config(config)
        self.assertIn("MISSING_SPEECH", str(ctx.exception))
        self.assertIn("[[speech]]", str(ctx.exception))

    def test_missing_image_key_raises(self) -> None:
        config = {"image": [{"api_key_env": "MISSING_IMG"}]}
        with mock.patch.dict(os.environ, {"MISSING_IMG": ""}):
            with self.assertRaises(LensException) as ctx:
                collect_api_key_secrets_for_lens_config(config)
        self.assertIn("MISSING_IMG", str(ctx.exception))
        self.assertIn("[[image]]", str(ctx.exception))

    def test_collect_all_projects_merges_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p_a = root / "a"
            p_b = root / "b"
            p_a.mkdir()
            p_b.mkdir()
            (p_a / "lens.toml").write_text(
                '[[llm]]\napi_key_env = "LLM_A"\nmodel = "x"\n',
                encoding="utf-8",
            )
            (p_b / "lens.toml").write_text(
                '[[image]]\napi_key_env = "IMG_B"\napi = "a2e"\nmodel = "a2e"\n',
                encoding="utf-8",
            )
            projects = [
                ("a", p_a, p_a),
                ("b", p_b, p_b),
            ]
            with mock.patch.dict(
                os.environ,
                {"LLM_A": "la", "IMG_B": "ib"},
                clear=False,
            ):
                got = collect_all_project_api_key_secrets(projects)
            self.assertEqual(got, {"LLM_A": "la", "IMG_B": "ib"})


if __name__ == "__main__":
    unittest.main()
