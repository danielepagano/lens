"""Unit tests for lens.core.turns.parse_passage_turns."""

from __future__ import annotations

import unittest

from lens.core.storage_text import normalize_storage_text
from lens.core.turns import parse_passage_turns


def _turns(raw: str) -> list[tuple[str, str]]:
    return parse_passage_turns(normalize_storage_text(raw))


class TestParsePassageTurns(unittest.TestCase):
    """Unit tests for parse_passage_turns."""

    def test_no_annotations_returns_empty(self) -> None:
        raw = "Just some text\nwith no annotations\n"
        self.assertEqual(_turns(raw), [])

    def test_only_open_annotation_returns_empty(self) -> None:
        raw = "[chat]: #\nPending response\n"
        self.assertEqual(_turns(raw), [])

    def test_single_pair_no_id_is_assistant(self) -> None:
        raw = "[chat]: #\nAI says something.\n[/chat]: #\n"
        turns = _turns(raw)
        self.assertEqual(turns, [("assistant", "AI says something.")])

    def test_content_outside_pair_is_user(self) -> None:
        raw = "> [Amy] Hello\n[chat]: #\nBob replies.\n[/chat]: #\n"
        turns = _turns(raw)
        self.assertEqual(turns, [
            ("user", "> [Amy] Hello"),
            ("assistant", "Bob replies."),
        ])

    def test_id_pair_is_user(self) -> None:
        raw = "[section:ch1]: #\nSummary of chapter one.\n[/section:ch1]: #\n"
        turns = _turns(raw)
        self.assertEqual(turns, [("user", "Summary of chapter one.")])

    def test_interleaved_user_assistant(self) -> None:
        raw = (
            "> [Amy] Hello\n"
            "[chat]: #\n"
            "Bob says hello.\n"
            "[/chat]: #\n"
            "> [Amy] And then?\n"
            "[chat]: #\n"
            "Bob responds again.\n"
            "[/chat]: #\n"
        )
        turns = _turns(raw)
        self.assertEqual(turns, [
            ("user", "> [Amy] Hello"),
            ("assistant", "Bob says hello."),
            ("user", "> [Amy] And then?"),
            ("assistant", "Bob responds again."),
        ])

    def test_adjacent_same_role_merged(self) -> None:
        """Two consecutive assistant annotations are merged into one turn."""
        raw = (
            "[chat]: #\nFirst response.\n[/chat]: #\n"
            "[chat]: #\nSecond response.\n[/chat]: #\n"
        )
        turns = _turns(raw)
        self.assertEqual(len(turns), 1)
        role, content = turns[0]
        self.assertEqual(role, "assistant")
        self.assertIn("First response.", content)
        self.assertIn("Second response.", content)

    def test_pending_open_annotation_content_is_user(self) -> None:
        """Content before a pending open annotation is user turn; pending content is user too."""
        raw = (
            "> [Amy] Hello\n"
            "[chat]: #\n"
            "Bob says hello.\n"
            "[/chat]: #\n"
            "> [Amy] Again?\n"
            "[chat]: #\n"
            "Bob pending response\n"
        )
        # The second [chat] has no close → no interval for it.
        # "Bob pending response" is outside any closed pair → user.
        turns = _turns(raw)
        # Should have: user(Amy hello), assistant(Bob), user(Amy again + Bob pending)
        self.assertEqual(turns[0], ("user", "> [Amy] Hello"))
        self.assertEqual(turns[1], ("assistant", "Bob says hello."))
        # Everything after the second [chat] annotation (which has no close) is user
        last_role, last_content = turns[-1]
        self.assertEqual(last_role, "user")
        self.assertIn("Again?", last_content)

    def test_whitespace_only_segments_dropped(self) -> None:
        raw = (
            "\n\n"
            "[chat]: #\n"
            "AI output.\n"
            "[/chat]: #\n"
            "\n\n"
        )
        turns = _turns(raw)
        self.assertEqual(turns, [("assistant", "AI output.")])

    def test_multiline_content_preserved(self) -> None:
        raw = (
            "[chat]: #\n"
            "Line one.\n"
            "Line two.\n"
            "[/chat]: #\n"
        )
        turns = _turns(raw)
        self.assertEqual(len(turns), 1)
        self.assertIn("Line one.", turns[0][1])
        self.assertIn("Line two.", turns[0][1])

    def test_multiline_annotation_header_handled(self) -> None:
        raw = (
            "[chat\n"
            "  as_kb_id: npc.bob\n"
            "]: #\n"
            "Bob says hello.\n"
            "[/chat]: #\n"
        )
        turns = _turns(raw)
        self.assertEqual(turns, [("assistant", "Bob says hello.")])

    def test_play_operator_pattern(self) -> None:
        """Player lines → user, GM narrative → assistant."""
        raw = (
            "> [Player] We enter the tavern.\n"
            "[play]: #\n"
            "The taproom is dim, smelling of sawdust.\n"
            "[/play]: #\n"
            "> [Player] I approach the bar.\n"
        )
        turns = _turns(raw)
        self.assertEqual(turns[0], ("user", "> [Player] We enter the tavern."))
        self.assertEqual(turns[1], ("assistant", "The taproom is dim, smelling of sawdust."))
        self.assertEqual(turns[2], ("user", "> [Player] I approach the bar."))

    def test_standalone_mount_image_line_removed_from_turns(self) -> None:
        raw = (
            "> [Amy] Look at this.\n"
            "![snap](/mount/file/pics/a.png)\n"
            "[chat]: #\n"
            "Nice photo.\n"
            "[/chat]: #\n"
        )
        turns = _turns(raw)
        self.assertEqual(turns[0], ("user", "> [Amy] Look at this."))
        self.assertEqual(turns[1], ("assistant", "Nice photo."))

    def test_section_summary_in_write_node(self) -> None:
        """Section summaries (id) inside a write node are user turns."""
        raw = (
            "[write]: #\n"
            "The hero crossed the bridge.\n"
            "[/write]: #\n"
            "[section:ch1]: #\n"
            "Earlier, the hero arrived in town.\n"
            "[/section:ch1]: #\n"
            "[write]: #\n"
            "She paused at the gate.\n"
            "[/write]: #\n"
        )
        turns = _turns(raw)
        # write → assistant, section:ch1 → user, write → assistant
        # Both write turns merge into one; section stays separate.
        roles = [r for r, _ in turns]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        user_turns = [(r, c) for r, c in turns if r == "user"]
        self.assertEqual(len(user_turns), 1)
        self.assertIn("arrived in town", user_turns[0][1])


if __name__ == "__main__":
    unittest.main()
