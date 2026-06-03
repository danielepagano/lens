"""Tests for attributed blockquote dialogue splitting."""

from __future__ import annotations

import unittest

from lens.core.modalities.catalog.attributed_dialogue import split_attributed_dialogue_line


class TestAttributedDialogueSplit(unittest.TestCase):
    def test_split_blockquote_line(self) -> None:
        split = split_attributed_dialogue_line("> [Riley] Wait [breath] you're serious?")
        self.assertIsNotNone(split)
        assert split is not None
        self.assertEqual(split.prefix, "> [Riley] ")
        self.assertEqual(split.body, "Wait [breath] you're serious?")

    def test_split_without_blockquote(self) -> None:
        split = split_attributed_dialogue_line("[Amy] Hello there.")
        self.assertIsNotNone(split)
        assert split is not None
        self.assertEqual(split.prefix, "[Amy] ")
        self.assertEqual(split.body, "Hello there.")

    def test_non_dialogue_returns_none(self) -> None:
        self.assertIsNone(split_attributed_dialogue_line("Plain narration."))


if __name__ == "__main__":
    unittest.main()
