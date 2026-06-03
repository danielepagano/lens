"""Unit tests for operator_applies_to_session dataset filtering helper."""

from __future__ import annotations

import unittest

from lens.core.project import operator_applies_to_session


class TestOperatorAppliesToSession(unittest.TestCase):
    """Tests for operator_applies_to_session selection logic."""

    def test_limited_empty_always_included(self) -> None:
        self.assertTrue(operator_applies_to_session([], []))
        self.assertTrue(operator_applies_to_session(["a", "b"], []))
        self.assertTrue(operator_applies_to_session(["testing"], []))

    def test_limited_nonempty_selected_empty_excluded(self) -> None:
        self.assertFalse(operator_applies_to_session([], ["testing"]))
        self.assertFalse(operator_applies_to_session([], ["a", "b"]))

    def test_both_nonempty_no_overlap_excluded(self) -> None:
        self.assertFalse(operator_applies_to_session(["a", "b"], ["c", "d"]))
        self.assertFalse(operator_applies_to_session(["testing"], ["play", "gm"]))

    def test_both_nonempty_overlap_included(self) -> None:
        self.assertTrue(operator_applies_to_session(["a", "b"], ["b", "c"]))
        self.assertTrue(operator_applies_to_session(["testing", "extra"], ["testing"]))
        self.assertTrue(operator_applies_to_session(["play"], ["play", "gm"]))
