"""Tests for ``lens.core.auto_compress``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.auto_compress import read_cursor_auto_compress_state
from lens.core.compression import CompressConfig
from lens.core.narrative import NarrativeNode


class TestReadCursorAutoCompressState(unittest.TestCase):
    def test_disabled_no_trigger_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lens.toml").write_text(
                '[project]\nnarrative = "n"\n[compress]\nauto_compress = false\n',
                encoding="utf-8",
            )
            narr = root / "narrative" / "n"
            narr.mkdir(parents=True)
            (narr / "_node.md").write_text("x" * 50_000, encoding="utf-8")
            from lens.core.project import ProjectSession

            session = ProjectSession(git_root=root, project_root=root)
            node = NarrativeNode(narrative_root=narr, key_path=())
            st = read_cursor_auto_compress_state(session, node)
            self.assertFalse(st.compress_on)
            self.assertIsNotNone(st.trigger)

    def test_enabled_and_small_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lens.toml").write_text('[project]\nnarrative = "n"\n', encoding="utf-8")
            narr = root / "narrative" / "n"
            narr.mkdir(parents=True)
            (narr / "_node.md").write_text("hello", encoding="utf-8")
            from lens.core.project import ProjectSession

            session = ProjectSession(git_root=root, project_root=root)
            node = NarrativeNode(narrative_root=narr, key_path=())
            st = read_cursor_auto_compress_state(session, node)
            self.assertTrue(st.compress_on)
            self.assertLess(st.visible_bytes, CompressConfig().m)
            self.assertIsNone(st.trigger)
