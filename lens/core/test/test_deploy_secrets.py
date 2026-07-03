"""Tests for Fly deploy secret collection (LLM + image + speech api_key_env
and dataset repo deploy keys)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.commands.deploy import (
    collect_all_project_api_key_secrets,
    collect_api_key_secrets_for_lens_config,
    collect_dataset_repo_deploy_key_secrets,
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


class DatasetRepoDeployKeySecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _project(self, name: str, toml_content: str) -> tuple[str, Path, Path]:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "lens.toml").write_text(toml_content, encoding="utf-8")
        return (name, p, p)

    def test_empty_when_no_dataset_repo(self) -> None:
        projects = [self._project("a", "[project]\ndatasets = []\n")]
        with mock.patch.dict(os.environ, {}, clear=True):
            got = collect_dataset_repo_deploy_key_secrets(projects)
        self.assertEqual(got, {})

    def test_collects_key_when_env_set(self) -> None:
        projects = [
            self._project(
                "a",
                '[[dataset_repo]]\nname = "my-dnd"\ngit_url = "git@github.com:user/dnd.git"\n',
            )
        ]
        with mock.patch.dict(os.environ, {"DATASET_REPO_DEPLOY_KEY_MY_DND": "key123"}, clear=True):
            got = collect_dataset_repo_deploy_key_secrets(projects)
        self.assertEqual(got, {"DATASET_REPO_DEPLOY_KEY_MY_DND": "key123"})

    def test_skips_when_env_not_set(self) -> None:
        projects = [
            self._project(
                "a",
                '[[dataset_repo]]\nname = "my-dnd"\ngit_url = "git@github.com:user/dnd.git"\n',
            )
        ]
        with mock.patch.dict(os.environ, {}, clear=True):
            got = collect_dataset_repo_deploy_key_secrets(projects)
        self.assertEqual(got, {})

    def test_deduplicates_same_name_across_projects(self) -> None:
        toml = '[[dataset_repo]]\nname = "shared"\ngit_url = "git@example.com:shared.git"\n'
        projects = [self._project("a", toml), self._project("b", toml)]
        with mock.patch.dict(os.environ, {"DATASET_REPO_DEPLOY_KEY_SHARED": "dup"}, clear=True):
            got = collect_dataset_repo_deploy_key_secrets(projects)
        self.assertEqual(got, {"DATASET_REPO_DEPLOY_KEY_SHARED": "dup"})

    def test_missing_secret_skipped(self) -> None:
        projects = [
            self._project(
                "a",
                '[[dataset_repo]]\nname = "my-dnd"\ngit_url = "git@github.com:user/dnd.git"\n'
                '[[dataset_repo]]\nname = "public-repo"\ngit_url = "https://example.com/pub.git"\n',
            )
        ]
        with mock.patch.dict(os.environ, {"DATASET_REPO_DEPLOY_KEY_MY_DND": "key123"}, clear=True):
            got = collect_dataset_repo_deploy_key_secrets(projects)
        self.assertEqual(got, {"DATASET_REPO_DEPLOY_KEY_MY_DND": "key123"})


if __name__ == "__main__":
    unittest.main()
