"""Tests for operator detection at a cursor (:mod:`lens.core.operator_detect`)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode
from lens.core.operator_detect import (
    detect_open_session_operator,
    detect_operator_name,
)


class TestDetectOperatorAncestry(unittest.TestCase):
    """The session tag is not always on the immediate parent."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lens_detect_ancestry_"))
        self.root = self.tmp / "narrative" / "story"
        (self.root / "sess").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _node(self, *keys: str) -> NarrativeNode:
        return NarrativeNode(narrative_root=self.root, key_path=tuple(keys))

    def test_session_on_the_immediate_parent(self) -> None:
        (self.root / "_node.md").write_text("# story\n\n[play:sess]: #\n", encoding="utf-8")
        (self.root / "sess" / "_node.md").write_text("> [Player] we go in\n", encoding="utf-8")
        self.assertEqual(detect_operator_name(self._node("sess")), "play")

    def test_session_on_a_grandparent(self) -> None:
        # `section start` inside a play session pushes the cursor a level
        # deeper; the play tag stays behind on the grandparent.
        (self.root / "_node.md").write_text("# story\n\n[play:sess]: #\n", encoding="utf-8")
        (self.root / "sess" / "_node.md").write_text(
            "> [Player] we go in\n\n[section:vault]: #\n", encoding="utf-8"
        )
        (self.root / "sess" / "vault.md").write_text("# vault\n\nDust.\n", encoding="utf-8")
        self.assertEqual(detect_operator_name(self._node("sess", "vault")), "play")

    def test_closed_session_does_not_own_the_node(self) -> None:
        (self.root / "_node.md").write_text(
            "# story\n\n[play:sess]: #\n\nSummary.\n\n[/play:sess]: #\n", encoding="utf-8"
        )
        (self.root / "sess" / "_node.md").write_text("Old turns.\n", encoding="utf-8")
        self.assertIsNone(detect_operator_name(self._node("sess")))

    def test_nearest_open_session_wins(self) -> None:
        (self.root / "_node.md").write_text("# story\n\n[design:sess]: #\n", encoding="utf-8")
        (self.root / "sess" / "chat").mkdir(parents=True)
        (self.root / "sess" / "_node.md").write_text("Planning.\n\n[chat:chat]: #\n", encoding="utf-8")
        (self.root / "sess" / "chat" / "_node.md").write_text("Talk.\n", encoding="utf-8")
        self.assertEqual(detect_operator_name(self._node("sess", "chat")), "chat")

    def test_own_annotation_decides_when_no_session_is_open(self) -> None:
        (self.root / "_node.md").write_text("# story\n\nPlain.\n", encoding="utf-8")
        (self.root / "sess" / "_node.md").write_text("Text.\n\n[write]: #\n", encoding="utf-8")
        self.assertEqual(detect_operator_name(self._node("sess")), "write")


class TestDetectOperatorInlineHistory(unittest.TestCase):
    """A finished inline turn still says what runs at this cursor."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lens_detect_inline_"))
        self.root = self.tmp / "narrative" / "story"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _detect(self, text: str) -> str | None:
        (self.root / "_node.md").write_text(text, encoding="utf-8")
        return detect_operator_name(NarrativeNode(narrative_root=self.root, key_path=()))

    def test_completed_inline_play_still_reports_play(self) -> None:
        # The state a report is almost always read in: the turn has closed, so
        # nothing is open, but the next call here is still play.
        self.assertEqual(
            self._detect("# story\n\n[play]: #\nThe gate groans.\n[/play]: #\n"), "play"
        )

    def test_free_text_after_a_closed_turn_does_not_reset_it(self) -> None:
        self.assertEqual(
            self._detect(
                "# story\n\n[play]: #\nThe gate groans.\n[/play]: #\n\nHand-typed note.\n"
            ),
            "play",
        )

    def test_most_recent_narrating_block_wins(self) -> None:
        self.assertEqual(
            self._detect(
                "# story\n\n[play]: #\nA.\n[/play]: #\n\n[write]: #\nB.\n[/write]: #\n"
            ),
            "write",
        )

    def test_structural_annotations_are_ignored(self) -> None:
        # A section tag between turns describes the tree, not what runs next.
        self.assertEqual(
            self._detect(
                "# story\n\n[play]: #\nA.\n[/play]: #\n\n[section:ch1/]: #\n"
            ),
            "play",
        )

    def test_no_narrating_history_at_all(self) -> None:
        self.assertIsNone(self._detect("# story\n\nJust prose I typed.\n"))


class TestDetectOpenSessionOperator(unittest.TestCase):
    """Only an *unclosed* session counts — this answer gates ``--end``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lens_detect_session_"))
        self.root = self.tmp / "narrative" / "story"
        (self.root / "sess").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _node(self, *keys: str) -> NarrativeNode:
        return NarrativeNode(narrative_root=self.root, key_path=tuple(keys))

    def test_session_on_the_immediate_parent(self) -> None:
        (self.root / "_node.md").write_text("# story\n\n[chat:sess]: #\n", encoding="utf-8")
        (self.root / "sess" / "_node.md").write_text("Talk.\n", encoding="utf-8")
        self.assertEqual(detect_open_session_operator(self._node("sess")), "chat")

    def test_session_on_a_grandparent(self) -> None:
        (self.root / "_node.md").write_text("# story\n\n[play:sess]: #\n", encoding="utf-8")
        (self.root / "sess" / "_node.md").write_text(
            "> [Player] we go in\n\n[section:vault]: #\n", encoding="utf-8"
        )
        (self.root / "sess" / "vault.md").write_text("# vault\n\nDust.\n", encoding="utf-8")
        self.assertEqual(detect_open_session_operator(self._node("sess", "vault")), "play")

    def test_closed_session_is_not_open(self) -> None:
        (self.root / "_node.md").write_text(
            "# story\n\n[play:sess]: #\n\nSummary.\n\n[/play:sess]: #\n", encoding="utf-8"
        )
        (self.root / "sess" / "_node.md").write_text("Old turns.\n", encoding="utf-8")
        self.assertIsNone(detect_open_session_operator(self._node("sess")))

    def test_completed_inline_turn_is_not_an_open_session(self) -> None:
        # detect_operator_name says "play" here; a session-close affordance
        # must not, because there is no session left to end.
        (self.root / "_node.md").write_text(
            "# story\n\n[play]: #\nThe gate groans.\n[/play]: #\n", encoding="utf-8"
        )
        self.assertIsNone(detect_open_session_operator(self._node()))
        self.assertEqual(detect_operator_name(self._node()), "play")

    def test_own_open_non_session_annotation_is_not_a_session(self) -> None:
        (self.root / "_node.md").write_text("# story\n\nText.\n\n[write]: #\n", encoding="utf-8")
        self.assertIsNone(detect_open_session_operator(self._node()))


if __name__ == "__main__":
    unittest.main()
