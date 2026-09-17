"""The proposal surface: ops, their line spans, their status, and the diff pair.

Once proposals are markdown comments, the node no longer *shows* what a session
is changing.  That is deliberate for the model and would be a regression for the
person, who could previously read the fences and diff each one.  These tests pin
the replacement, including the case the fences never covered: a stack that has
gone stale under a direct edit has to say so, on every read.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.kb_pending_view import (
    format_pending_lines,
    pending_kb_view,
    pending_payload,
)
from lens.core.kb_pending import KbOp, render_kb_ops
from lens.core.knowledge import KnowledgeStore


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


class _ViewCase(unittest.TestCase):
    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "t@t.com")
        _git(self.root, "config", "user.name", "T")
        (self.root / "lens.toml").write_text('[project]\nnarrative = "story"\n')
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge" / "tags.toml").write_text("")
        node_dir = self.root / "narrative" / "story"
        node_dir.mkdir(parents=True)
        self.cursor = node_dir / "_node.md"
        self.cursor.write_text("[\n  kb_pin: []\n]: #\n\nPROLOGUE\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "init")
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def propose(self, *ops: KbOp) -> None:
        block = render_kb_ops(ops)
        self.cursor.write_text(
            f"{self.cursor.read_text()}\n[design\n  prompt: build\n]: #\n\n"
            f"Prose.\n\n{block}\n[/design]: #\n"
        )
        self.store.evict_pending()


class TestPendingView(_ViewCase):
    def test_no_session_means_an_empty_view(self) -> None:
        self.assertTrue(pending_kb_view(self.root).is_empty())
        self.assertEqual(
            format_pending_lines(pending_kb_view(self.root)),
            ["No pending KB proposals at the cursor."],
        )

    def test_every_op_is_listed_with_its_line_span(self) -> None:
        self.propose(
            KbOp(op="add", id="loc.vault", body="# The Vault\n\nSealed.\n"),
            KbOp(op="tag", id="loc.vault", tags=("sunken",), remove_tags=("draft",)),
        )
        view = pending_kb_view(self.root)

        self.assertEqual([op.op for op in view.ops], ["add", "tag"])
        self.assertTrue(all(op.status == "ok" for op in view.ops))
        lines = self.cursor.read_text().split("\n")
        for op in view.ops:
            # The span is what makes a proposal editable by hand or by a client.
            self.assertTrue(lines[op.line_start - 1].lstrip().startswith("[kb-op"))
            self.assertTrue(lines[op.line_end - 1].rstrip().endswith("]: #"))

    def test_summaries_say_what_each_op_does(self) -> None:
        self.propose(
            KbOp(op="add", id="loc.vault", body="one\ntwo\n"),
            KbOp(op="tag", id="loc.vault", tags=("sunken",), remove_tags=("draft",)),
            KbOp(op="remove", id="loc.vault"),
        )
        summaries = [op.summary for op in pending_kb_view(self.root).ops]
        self.assertIn("whole body", summaries[0])
        self.assertEqual(summaries[1], "+sunken -draft")
        self.assertEqual(summaries[2], "delete")

    def test_a_created_object_carries_no_base(self) -> None:
        self.propose(KbOp(op="add", id="loc.vault", body="Sealed.\n"))
        obj = pending_kb_view(self.root).objects[0]
        self.assertEqual((obj.id, obj.change), ("loc.vault", "created"))
        self.assertIsNone(obj.base)
        self.assertEqual(obj.proposed, "Sealed.\n")

    def test_a_patched_object_carries_both_sides_of_the_diff(self) -> None:
        self.store.store_object("loc.vault", "alpha\nbeta\n")
        self.propose(
            KbOp(
                op="patch",
                id="loc.vault",
                patches=({"start": {"target": "beta"}, "content": "BETA"},),
            )
        )
        obj = pending_kb_view(self.root).objects[0]
        self.assertEqual(obj.change, "updated")
        self.assertEqual(obj.base, "alpha\nbeta\n")
        self.assertIn("BETA", obj.proposed or "")
        self.assertEqual(obj.base_source, "project")

    def test_a_removed_object_carries_the_base_it_would_lose(self) -> None:
        self.store.store_object("loc.vault", "going away\n")
        self.propose(KbOp(op="remove", id="loc.vault"))
        obj = pending_kb_view(self.root).objects[0]
        self.assertEqual(obj.change, "removed")
        self.assertEqual(obj.base, "going away\n")
        self.assertIsNone(obj.proposed)

    def test_payload_is_json_shaped(self) -> None:
        import json

        self.propose(KbOp(op="add", id="loc.vault", body="Sealed.\n"))
        payload = pending_payload(pending_kb_view(self.root))
        json.dumps(payload)  # must not raise
        self.assertEqual(payload["ops"][0]["id"], "loc.vault")
        self.assertEqual(payload["objects"][0]["change"], "created")


class TestStaleStackIsVisible(_ViewCase):
    """A direct edit can invalidate a proposal; it must be loud about it."""

    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("loc.vault", "the anchor line\n")
        self.propose(
            KbOp(
                op="patch",
                id="loc.vault",
                patches=({"start": {"target": "the anchor line"}, "content": "new"},),
            )
        )

    def test_valid_while_the_anchor_is_there(self) -> None:
        view = pending_kb_view(self.root)
        self.assertEqual(view.ops[0].status, "ok")
        self.assertEqual(view.errors, [])

    def test_a_direct_edit_that_removes_the_anchor_is_reported(self) -> None:
        (self.root / "knowledge" / "loc" / "vault.md").write_text("rewritten by hand\n")
        self.store.evict_pending()

        view = pending_kb_view(self.root)
        self.assertEqual(view.ops[0].status, "error")
        self.assertIn("target line not found", view.ops[0].error)
        self.assertEqual(len(view.errors), 1)

    def test_the_error_names_the_block_to_go_and_fix(self) -> None:
        (self.root / "knowledge" / "loc" / "vault.md").write_text("rewritten by hand\n")
        self.store.evict_pending()

        op = pending_kb_view(self.root).ops[0]
        lines = self.cursor.read_text().split("\n")
        self.assertTrue(lines[op.line_start - 1].lstrip().startswith("[kb-op"))

    def test_deleting_the_block_by_hand_clears_the_error(self) -> None:
        # Correcting a proposal needs no machinery: the ops are plain text and
        # the fold re-reads the node.
        (self.root / "knowledge" / "loc" / "vault.md").write_text("rewritten by hand\n")
        self.store.evict_pending()
        self.assertEqual(len(pending_kb_view(self.root).errors), 1)

        text = self.cursor.read_text()
        start = text.index("[kb-op")
        end = text.index("]: #", start) + len("]: #")
        self.cursor.write_text(text[:start] + text[end:])
        self.store.evict_pending()

        self.assertTrue(pending_kb_view(self.root).is_empty())

    def test_a_rendered_error_line_is_marked(self) -> None:
        (self.root / "knowledge" / "loc" / "vault.md").write_text("rewritten by hand\n")
        self.store.evict_pending()
        lines = format_pending_lines(pending_kb_view(self.root))
        self.assertTrue(any(line.startswith("!") for line in lines))


if __name__ == "__main__":
    unittest.main()
