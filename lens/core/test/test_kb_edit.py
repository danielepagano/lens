"""Unit tests for kb_edit core function."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.annotations import encode_ai_secrets
from lens.core.commands.kb import kb_edit
from lens.core.exceptions import LensException
from lens.core.llm_run import LlmRunRequest
from lens.core.test.llm_run_mock import prose_artifacts, run_llm_from_text


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test", with_llm: bool = True) -> Path:
    toml = f'[project]\nnarrative = "{slug}"\n'
    if with_llm:
        toml += '''
[[llm]]
base_url = "http://127.0.0.1:9999"
model = "test"
api_key_env = "OPENAI_API_KEY"
'''
    (tmp / "lens.toml").write_text(toml)
    (tmp / "narrative" / slug).mkdir(parents=True)
    (tmp / "narrative" / slug / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _run_in_project(root: Path, fn: Any, *args: Any, **kwargs: Any) -> Any:
    old_cwd = os.getcwd()
    try:
        os.chdir(root)
        return fn(*args, **kwargs)
    finally:
        os.chdir(old_cwd)


class TestKbEditValidation(unittest.TestCase):
    def test_rejects_template_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            with patch(
                "lens.core.commands.kb.run_llm",
                new=run_llm_from_text("New content"),
            ):
                with self.assertRaises(LensException) as ctx:
                    _run_in_project(root, kb_edit, "person._template", "add name", pins=[], unpins=[])
                self.assertIn("template", str(ctx.exception).lower())

    def test_context_in_dataset_mode_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "lens.toml").write_text("[dataset]\n")
            (root / "knowledge").mkdir(exist_ok=True)
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "ds"], cwd=root, capture_output=True, check=True)
            with patch(
                "lens.core.commands.kb.run_llm",
                new=run_llm_from_text("New content"),
            ):
                with self.assertRaises(LensException) as ctx:
                    _run_in_project(
                        root, kb_edit, "person.amy", "edit",
                        context_address="/x", pins=[], unpins=[],
                    )
                self.assertIn("not available in dataset mode", str(ctx.exception))

    def test_invalid_object_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            with self.assertRaises(LensException):
                _run_in_project(root, kb_edit, "invalid-id", "edit", pins=[], unpins=[])


class TestKbEditCrawlResolution(unittest.TestCase):
    def test_without_context_uses_crawl_result_from_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "person").mkdir(exist_ok=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Amy.")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "kb"], cwd=root, capture_output=True, check=True)

            messages_captured: list[Any] = []

            async def capture_run(request: LlmRunRequest, **kwargs: Any) -> Any:
                messages_captured.append(request.messages or [])
                return prose_artifacts("OK")

            with patch("lens.core.commands.kb.run_llm", new=capture_run):
                _run_in_project(root, kb_edit, "person.new", "create", pins=["person.amy"], unpins=[])

            self.assertEqual(len(messages_captured), 1)
            msgs = messages_captured[0]
            user_content = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            self.assertIn("person.amy", user_content)
            self.assertIn("Amy", user_content)


class TestKbEditStorage(unittest.TestCase):
    def test_new_item_stores_llm_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            with patch(
                "lens.core.commands.kb.run_llm",
                new=run_llm_from_text("New content"),
            ):
                _run_in_project(root, kb_edit, "person.hero", "create a hero", pins=[], unpins=[])

            path = root / "knowledge" / "person" / "hero.md"
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), "New content")

    def test_existing_item_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "person").mkdir(exist_ok=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Original")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "kb"], cwd=root, capture_output=True, check=True)

            with patch(
                "lens.core.commands.kb.run_llm",
                new=run_llm_from_text("Updated"),
            ):
                _run_in_project(root, kb_edit, "person.amy", "update", pins=[], unpins=[])

            path = root / "knowledge" / "person" / "amy.md"
            self.assertEqual(path.read_text(), "Updated")

    def test_encode_ai_secrets_before_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            secret_text = "plain"
            raw_output = f"Public part\n\n<!-- ai:secret:\n{secret_text}\n-->"
            encoded_output = encode_ai_secrets(raw_output)
            with patch(
                "lens.core.commands.kb.run_llm",
                new=run_llm_from_text(encoded_output),
            ):
                _run_in_project(root, kb_edit, "person.x", "add secret", pins=[], unpins=[])

            path = root / "knowledge" / "person" / "x.md"
            stored = path.read_text()
            self.assertIn("<!-- ai:secret:", stored)
            self.assertNotIn("plain", stored)
            self.assertIn("cynva", stored)
