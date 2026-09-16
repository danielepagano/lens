"""A design session proposing KB writes, end to end against the fake LLM.

Sequential: state accumulates and method names force the order.  These are the
acceptance cases from #161 that only the whole stack can answer — the tool call
has to go through the real LLM loop, the block has to be persisted by the real
compose path, and the overlay has to be derived from the real cursor.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.annotations import strip_markdown_comments
from lens.core.kb_pending import parse_kb_ops
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operators.design import DesignOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.testing.fake_llm import KB_OP_TRIGGER, FakeLLMServer
from lens.testing.project import setup_test_project


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _trigger(*calls: dict[str, Any]) -> str:
    payload = list(calls) if len(calls) != 1 else calls[0]
    return f"{KB_OP_TRIGGER} {json.dumps(payload)}"


class TestKbOpsSession(unittest.TestCase):
    _server: FakeLLMServer
    _project_dir: Path
    _orig_cwd: Path
    _keep_dir: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._project_dir = Path(tempfile.mkdtemp(prefix="lens_kb_ops_"))
        cls._orig_cwd = Path.cwd()
        setup_test_project(cls._project_dir, cls._server.base_url, dataset="testing")
        os.chdir(cls._project_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._orig_cwd)
        cls._server.stop()
        if cls._keep_dir:
            print(f"\n[itest] project preserved: {cls._project_dir}")
        else:
            shutil.rmtree(str(cls._project_dir), ignore_errors=True)

    def tearDown(self) -> None:
        result = getattr(getattr(self, "_outcome", None), "result", None)
        if result is not None:
            if getattr(result, "failures", []) or getattr(result, "errors", []):
                TestKbOpsSession._keep_dir = True

    def _session(self) -> ProjectSession:
        KnowledgeStore.clear_registry()
        return ProjectSession(self._project_dir, self._project_dir)

    def _narrative(self, session: ProjectSession) -> NarrativeNode:
        narrative = session.active_narrative
        assert narrative is not None
        return narrative

    def _cursor_text(self) -> str:
        session = self._session()
        return self._narrative(session).find_cursor().md_path().read_text()

    def _checkpoint(self, msg: str) -> None:
        Storage(self._project_dir).commit(msg)

    # ------------------------------------------------------------------

    def test_01_a_proposal_lands_in_the_node_and_nowhere_else(self) -> None:
        session = self._session()
        _run(DesignOperator.run_design(
            session=session,
            narrative=self._narrative(session),
            prompt=_trigger({
                "tool": "kb_add",
                "arguments": {"id": "loc.vault", "body": "# The Vault\n\nSealed.\n"},
            }),
            module_ids=None,
            pins=[],
            unpins=[],
            llm_id="mock",
            slug="vault",
        ))

        text = self._cursor_text()
        ops = parse_kb_ops(text)
        self.assertEqual([(op.op, op.id) for op in ops], [("add", "loc.vault")])
        self.assertEqual(ops[0].body, "# The Vault\n\nSealed.\n")
        self.assertFalse((self._project_dir / "knowledge" / "loc" / "vault.md").exists())

    def test_02_the_block_is_invisible_to_the_model(self) -> None:
        text = self._cursor_text()
        visible = strip_markdown_comments(text)
        self.assertNotIn("kb-op", visible)
        self.assertNotIn("The Vault", visible)

    def test_03_no_tool_call_fence_duplicates_the_body(self) -> None:
        # The [kb-op] block is the record; a fence beside it would sit in the
        # assistant turn every later beat reads back.
        text = self._cursor_text()
        self.assertNotIn("```tool-call", text)

    def test_04_the_proposal_is_the_store_reality(self) -> None:
        store = self._session().kb
        self.assertTrue(store.exists("loc.vault"))
        self.assertIn("Sealed.", store.get_objects(["loc.vault"])["loc.vault"].text)
        self.assertIn("loc.vault", store.list_ids())
        source = store.describe_source("loc.vault")
        self.assertIsNotNone(source)
        self.assertEqual((source and source.kind), "pending")

    def test_05_the_block_sits_inside_the_operator_block(self) -> None:
        # This is the structural reason retry leaves no KB trace: write_discard
        # truncates from the open tag down, so anything below it goes with the
        # attempt.  Module includes go *above* the tag for the opposite reason.
        text = self._cursor_text()
        open_tag = text.index("[design")
        block = text.index("[kb-op")
        close_tag = text.index("[/design")
        self.assertLess(open_tag, block)
        self.assertLess(block, close_tag)

    def test_06_discarding_the_turn_discards_the_proposal(self) -> None:
        session = self._session()
        narrative = self._narrative(session)
        cursor = narrative.find_cursor()
        op = DesignOperator(session.new_storage(), narrative)
        ann = op.find_open_annotation(cursor)
        assert ann is not None

        op.write_discard(cursor, ann)

        self.assertEqual(parse_kb_ops(cursor.md_path().read_text()), [])
        self.assertFalse(self._session().kb.exists("loc.vault"))
        self.assertFalse((self._project_dir / "knowledge" / "loc" / "vault.md").exists())

    def test_07_a_turn_that_only_proposes_still_counts_as_content(self) -> None:
        # A tool-call-only turn produces no prose; if kb_ops did not count as
        # content the operator would raise "no content generated" and the
        # proposal would be rolled back with it.
        session = self._session()
        _run(DesignOperator.run_design(
            session=session,
            narrative=self._narrative(session),
            prompt=_trigger(
                {
                    "tool": "kb_add",
                    "arguments": {"id": "loc.vault", "body": "# The Vault\n"},
                },
                {
                    "tool": "kb_tag",
                    "arguments": {"id": "loc.vault", "tags": ["sunken"]},
                },
            ),
            module_ids=None,
            pins=[],
            unpins=[],
            llm_id="mock",
        ))

        ops = parse_kb_ops(self._cursor_text())
        self.assertEqual([op.op for op in ops], ["add", "tag"])
        store = self._session().kb
        self.assertEqual(store.get_tags("loc.vault"), ["sunken"])
        self.assertIn("loc.vault", store.get_ids_with_tag("sunken"))

    def test_08_a_failed_call_writes_no_proposal(self) -> None:
        before = len(parse_kb_ops(self._cursor_text()))
        session = self._session()
        _run(DesignOperator.run_design(
            session=session,
            narrative=self._narrative(session),
            prompt=_trigger({
                "tool": "kb_patch",
                "arguments": {
                    "id": "loc.vault",
                    "patches": [
                        {"start": {"target": "no such line"}, "content": "x"}
                    ],
                },
            }),
            module_ids=None,
            pins=[],
            unpins=[],
            llm_id="mock",
        ))

        text = self._cursor_text()
        self.assertEqual(len(parse_kb_ops(text)), before)
        # The failure still leaves its audit trail — there is no block behind it.
        self.assertIn("```tool-result", text)

    def test_09_navigating_away_leaves_the_proposals_intact_and_unwritten(self) -> None:
        from lens.core.commands.use import use_narrative

        cursor_before = self._cursor_text()
        (self._project_dir / "narrative" / "other").mkdir(parents=True, exist_ok=True)
        (self._project_dir / "narrative" / "other" / "_node.md").write_text("Elsewhere\n")
        use_narrative("other")
        try:
            store = self._session().kb
            self.assertFalse(store.exists("loc.vault"))
            self.assertFalse(
                (self._project_dir / "knowledge" / "loc" / "vault.md").exists()
            )
        finally:
            use_narrative("story")

        self.assertEqual(self._cursor_text(), cursor_before)
        self.assertTrue(self._session().kb.exists("loc.vault"))


if __name__ == "__main__":
    unittest.main()
