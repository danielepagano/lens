"""Tests for apply_remember_patches (remember-at-summary)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from lens.core.context import CrawlResult
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError
from lens.core.operators.session import (
    apply_remember_patches,
    format_remember_llm_output_for_child,
)


def _fake_tool_call_fence(
    name: str,
    arguments: dict[str, object],
    *,
    response_char_len: int | None,
) -> str:
    """Match ``lens.core.llm._format_tool_call_markdown`` output shape."""
    req = json.dumps(arguments, indent=2, ensure_ascii=False, default=str)
    lines = [
        "```tool-call",
        f"Called Tool '{name}' ({response_char_len if response_char_len else 'zero'} bytes)",
        req,
        "```",
    ]
    return "\n".join(lines) + "\n"


def _init_repo(tmp: Path) -> None:
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


def _make_remember_project(tmp: Path) -> Path:
    slug = "story"
    (tmp / "lens.toml").write_text(
        f'[project]\nnarrative = "{slug}"\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n',
        encoding="utf-8",
    )
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n", encoding="utf-8")

    kb = tmp / "knowledge"
    (kb / "lore").mkdir(parents=True)
    (kb / "lore" / "alice.md").write_text(
        "## Notes\nAlice prefers tea.\n", encoding="utf-8"
    )
    (kb / "remember").mkdir(parents=True)
    (kb / "remember" / "core-memories.md").write_text(
        "Track durable facts about the character.\n", encoding="utf-8"
    )
    (kb / "core-memories").mkdir(parents=True)
    (kb / "core-memories" / "_template.md").write_text(
        "## Core memories\n- \n", encoding="utf-8"
    )

    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "kb"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp


class TestApplyRememberPatches(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _init_repo(self.root)
        _make_remember_project(self.root)
        KnowledgeStore.clear_registry()
        store = KnowledgeStore.for_project(self.root)
        err = store.add_tags("lore.alice", ["remember.core-memories"])
        self.assertIsNone(err)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def test_returns_empty_when_no_pins(self) -> None:
        gen = AsyncMock(return_value="")

        async def _run() -> str:
            crawl = CrawlResult(
                knowledge=[],
                previous_summaries=[],
                current_content=None,
                project_root=self.root,
                pinned_ids=[],
            )
            return await apply_remember_patches(
                crawl_result=crawl,
                content="Some passage.",
                project_root=self.root,
            )

        with patch("lens.core.operators.session.generate_text", gen):
            out = asyncio.run(_run())
        self.assertEqual(out, "")
        gen.assert_not_awaited()

    def test_returns_empty_when_pins_have_no_remember_tags(self) -> None:
        gen = AsyncMock(return_value="")

        async def _run() -> str:
            store = KnowledgeStore.for_project(self.root)
            kb_line = store.get_objects(["lore.alice"])["lore.alice"].format()
            crawl = CrawlResult(
                knowledge=[kb_line],
                previous_summaries=[],
                current_content=None,
                project_root=self.root,
                pinned_ids=["lore.alice"],
            )
            store.remove_tags("lore.alice", ["remember.core-memories"])
            return await apply_remember_patches(
                crawl_result=crawl,
                content="Passage.",
                project_root=self.root,
            )

        with patch("lens.core.operators.session.generate_text", gen):
            out = asyncio.run(_run())
        self.assertEqual(out, "")
        gen.assert_not_awaited()
        KnowledgeStore.for_project(self.root).add_tags(
            "lore.alice", ["remember.core-memories"]
        )

    def test_task_lists_ids_only_not_full_instruction_repeat(self) -> None:
        captured: dict[str, Any] = {}

        async def _capture(
            messages: list[dict[str, Any]], _pr: Path, **kwargs: Any
        ) -> str:
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return ""

        store = KnowledgeStore.for_project(self.root)
        alice_fmt = store.get_objects(["lore.alice"])["lore.alice"].format()
        crawl = CrawlResult(
            knowledge=[alice_fmt],
            previous_summaries=[],
            current_content=None,
            project_root=self.root,
            pinned_ids=["lore.alice"],
        )

        with patch("lens.core.operators.session.generate_text", _capture):
            out = asyncio.run(
                apply_remember_patches(
                    crawl_result=crawl,
                    content="Alice said she now prefers coffee.",
                    project_root=self.root,
                )
            )

        self.assertEqual(out, "")
        user = captured["messages"][1]["content"]
        self.assertIn("--- begin TASK ---", user)
        self.assertIn(
            "- `remember.core-memories` and `core-memories._template`",
            user,
        )
        self.assertIn(
            "- lore.alice (remember via: remember.core-memories)",
            user,
        )
        self.assertIn("PASSAGE TO PROCESS:", user)
        self.assertIn("Alice said she now prefers coffee.", user)
        self.assertNotIn("Track durable facts", user.split("--- begin TASK ---")[1])

    def test_inlines_unpinned_instruction_kb_once(self) -> None:
        captured: dict[str, Any] = {}

        async def _capture(
            messages: list[dict[str, Any]], _pr: Path, **kwargs: Any
        ) -> str:
            captured["messages"] = messages
            return ""

        store = KnowledgeStore.for_project(self.root)
        alice_fmt = store.get_objects(["lore.alice"])["lore.alice"].format()
        crawl = CrawlResult(
            knowledge=[alice_fmt],
            previous_summaries=[],
            current_content=None,
            project_root=self.root,
            pinned_ids=["lore.alice"],
        )

        with patch("lens.core.operators.session.generate_text", _capture):
            asyncio.run(
                apply_remember_patches(
                    crawl_result=crawl,
                    content="x",
                    project_root=self.root,
                )
            )

        user = captured["messages"][1]["content"]
        self.assertIn("REMEMBER OBJECTS", user)
        self.assertIn("Track durable facts about the character.", user)
        before_task, task_part = user.split("--- begin TASK ---", 1)
        self.assertIn("RELEVANT KNOWLEDGE", before_task)
        self.assertIn("--- begin REMEMBER OBJECTS", before_task)
        self.assertLess(
            user.index("--- begin REMEMBER OBJECTS"),
            user.index("--- begin TASK ---"),
        )
        self.assertNotIn("Track durable facts", task_part)

    def test_no_remember_extra_section_when_instruction_and_template_pinned(
        self,
    ) -> None:
        captured: dict[str, Any] = {}

        async def _capture(
            messages: list[dict[str, Any]], _pr: Path, **kwargs: Any
        ) -> str:
            captured["messages"] = messages
            return ""

        store = KnowledgeStore.for_project(self.root)
        ids = ["lore.alice", "remember.core-memories", "core-memories._template"]
        objs = store.get_objects(ids)
        knowledge = [objs[i].format() for i in ids]
        crawl = CrawlResult(
            knowledge=knowledge,
            previous_summaries=[],
            current_content=None,
            project_root=self.root,
            pinned_ids=list(ids),
        )

        with patch("lens.core.operators.session.generate_text", _capture):
            asyncio.run(
                apply_remember_patches(
                    crawl_result=crawl,
                    content="y",
                    project_root=self.root,
                )
            )

        user = captured["messages"][1]["content"]
        self.assertNotIn("--- begin REMEMBER OBJECTS", user)
        self.assertIn("--- begin TASK ---", user)
        self.assertIn("core-memories._template", user.split("--- begin TASK ---")[1])

    def test_passes_kb_patch_whitelist_tools(self) -> None:
        captured: dict[str, Any] = {}

        async def _capture(
            _messages: list[dict[str, Any]], _pr: Path, **kwargs: Any
        ) -> str:
            captured.update(kwargs)
            return ""

        store = KnowledgeStore.for_project(self.root)
        alice_fmt = store.get_objects(["lore.alice"])["lore.alice"].format()
        crawl = CrawlResult(
            knowledge=[alice_fmt],
            previous_summaries=[],
            current_content=None,
            project_root=self.root,
            pinned_ids=["lore.alice"],
        )

        with patch("lens.core.operators.session.generate_text", _capture):
            asyncio.run(
                apply_remember_patches(
                    crawl_result=crawl,
                    content="z",
                    project_root=self.root,
                )
            )

        tools_raw = captured.get("tools")
        self.assertIsInstance(tools_raw, list)
        tools_list = cast(list[dict[str, Any]], tools_raw)
        names: list[str] = []
        for e in tools_list:
            fn_any = e.get("function")
            if not isinstance(fn_any, dict):
                continue
            fn = cast(dict[str, Any], fn_any)
            name_val = fn.get("name")
            if not isinstance(name_val, str):
                continue
            names.append(name_val)
        self.assertEqual(names, ["kb_patch"])
        self.assertEqual(captured.get("operator_name"), "remember")
        handlers = captured.get("command_tool_handlers")
        self.assertIsNotNone(handlers)
        assert handlers is not None
        self.assertIn("kb_patch", handlers)

    def test_format_remember_keeps_tool_fences(self) -> None:
        fence = _fake_tool_call_fence(
            "kb_patch",
            {"target_id": "lore.alice", "patch": "---\n"},
            response_char_len=12,
        )
        out = format_remember_llm_output_for_child(f"  \n{fence}  ")
        self.assertIn("```tool-call", out)
        self.assertIn("Called Tool 'kb_patch'", out)
        self.assertNotIn("<!-- remember:", out)

    def test_format_remember_wraps_stray_prose_beside_tools(self) -> None:
        fence = _fake_tool_call_fence(
            "kb_patch", {"target_id": "x", "patch": "y"}, response_char_len=0
        )
        raw = f"I updated memory.\n\n{fence}\nTrailing note."
        out = format_remember_llm_output_for_child(raw)
        self.assertIn("```tool-call", out)
        self.assertIn("<!-- remember:", out)
        self.assertIn("I updated memory", out)
        self.assertIn("Trailing note", out)

    def test_apply_remember_llm_error_suffix(self) -> None:
        async def _boom(
            *_a: Any, **_k: Any,
        ) -> str:
            raise LLMError("upstream refused")

        async def _run() -> str:
            store = KnowledgeStore.for_project(self.root)
            alice_fmt = store.get_objects(["lore.alice"])["lore.alice"].format()
            crawl = CrawlResult(
                knowledge=[alice_fmt],
                previous_summaries=[],
                current_content=None,
                project_root=self.root,
                pinned_ids=["lore.alice"],
            )
            return await apply_remember_patches(
                crawl_result=crawl,
                content="z",
                project_root=self.root,
            )

        with patch("lens.core.operators.session.generate_text", _boom):
            out = asyncio.run(_run())
        self.assertIn("<!-- remember: error:", out)
        self.assertIn("upstream refused", out)
