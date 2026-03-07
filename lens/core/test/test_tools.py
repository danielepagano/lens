"""Unit tests for tool registry and dataset filtering."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.tools import (
    OperatorToolDef,
    _TOOL_REGISTRY,  # pyright: ignore[reportPrivateUsage]
    get_tool_registry,
    operator_applies_to_session,
    register_operator_tool,
)


def _dummy_fn(*args: object) -> None:
    pass


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


class TestGetToolRegistryFiltering(unittest.TestCase):
    """Tests for get_tool_registry filtering by project datasets."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self._saved = dict(_TOOL_REGISTRY)
        _TOOL_REGISTRY.clear()

    def tearDown(self) -> None:
        _TOOL_REGISTRY.clear()
        _TOOL_REGISTRY.update(self._saved)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _tdef(self) -> OperatorToolDef:
        return OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet="test",
            keep_text=True,
        )

    def test_none_project_root_returns_all(self) -> None:
        register_operator_tool("unrestricted", self._tdef(), _dummy_fn, limited_to_datasets=[])
        register_operator_tool("restricted", self._tdef(), _dummy_fn, limited_to_datasets=["play"])
        reg = get_tool_registry(None)
        self.assertIn("unrestricted", reg)
        self.assertIn("restricted", reg)

    def test_project_no_datasets_excludes_limited_operators(self) -> None:
        (self.root / "lens.toml").write_text("[project]\n")
        register_operator_tool("unrestricted", self._tdef(), _dummy_fn, limited_to_datasets=[])
        register_operator_tool("restricted", self._tdef(), _dummy_fn, limited_to_datasets=["play"])
        reg = get_tool_registry(self.root)
        self.assertIn("unrestricted", reg)
        self.assertNotIn("restricted", reg)

    def test_project_with_matching_dataset_includes_limited_operator(self) -> None:
        (self.root / "lens.toml").write_text(
            '[project]\ndatasets = ["play", "other"]\n'
        )
        register_operator_tool("restricted", self._tdef(), _dummy_fn, limited_to_datasets=["play"])
        reg = get_tool_registry(self.root)
        self.assertIn("restricted", reg)

    def test_project_without_matching_dataset_excludes_limited_operator(self) -> None:
        (self.root / "lens.toml").write_text(
            '[project]\ndatasets = ["write", "other"]\n'
        )
        register_operator_tool("restricted", self._tdef(), _dummy_fn, limited_to_datasets=["play"])
        reg = get_tool_registry(self.root)
        self.assertNotIn("restricted", reg)
