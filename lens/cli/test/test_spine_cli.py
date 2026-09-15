"""Tests for the ``lens spine`` CLI adapter."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

ROOT_PROSE = "The kingdom had been at peace for a hundred years."
CHAPTER_PROSE = "Amy reached the dungeon gate at dusk and found it already open."
SCENE_PROSE = "The hinges had been cut, not forced."


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _run(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_LENS_CMD, "spine", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )


def _write(root: Path, keys: tuple[str, ...], text: str) -> None:
    path = root.joinpath(*keys) / "_node.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestSpineCli(unittest.TestCase):
    project_dir: Path
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        from lens.testing.project import setup_test_project

        cls.tmp = tempfile.mkdtemp(prefix="lens_spine_cli_")
        cls.project_dir = Path(cls.tmp)
        session = setup_test_project(
            cls.project_dir, "http://127.0.0.1:1/v1", opening_write=False
        )
        narrative = session.active_narrative
        assert narrative is not None
        root: Path = narrative.narrative_root
        _write(
            root,
            (),
            "[\n    kb_pin:\n    - person.amy\n]: #\n\n"
            f"{ROOT_PROSE}\n\n[section:chapter-1]: #\n",
        )
        _write(root, ("chapter-1",), f"{CHAPTER_PROSE}\n\n[section:scene-2]: #\n")
        _write(
            root,
            ("chapter-1", "scene-2"),
            f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
        )
        # Sanity: the fixture really does put the cursor at the leaf.
        assert (
            NarrativeNode(narrative_root=root, key_path=()).find_cursor().key_path
            == ("chapter-1", "scene-2")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_prints_every_node_on_the_spine_with_its_prose(self) -> None:
        result = _run(self.project_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = _strip_ansi(result.stdout)
        self.assertIn("Spine at story/chapter-1/scene-2", out)
        self.assertIn("Next generation here: write", out)
        for prose in (ROOT_PROSE, CHAPTER_PROSE, SCENE_PROSE):
            self.assertIn(prose, out)
        self.assertIn("(cursor)", out)

    def test_the_cursor_node_is_labelled_current_and_ancestors_summary(self) -> None:
        out = _strip_ansi(_run(self.project_dir).stdout)
        self.assertIn("story · summary", out)
        self.assertIn("story/chapter-1/scene-2 (cursor) · current", out)

    def test_outline_lists_sizes_without_the_prose(self) -> None:
        out = _strip_ansi(_run(self.project_dir, "--outline").stdout)
        self.assertIn("NODE", out)
        self.assertIn("tokens", out)
        # The opening line is a scannable excerpt; the body is not printed.
        self.assertIn("scene-2 (cursor)", out)
        self.assertNotIn(CHAPTER_PROSE, out)

    def test_text_prints_the_prose_alone(self) -> None:
        out = _run(self.project_dir, "--text").stdout
        self.assertNotIn("Spine at", out)
        self.assertNotIn("──", out)
        self.assertIn(ROOT_PROSE, out)
        self.assertIn(SCENE_PROSE, out)
        self.assertLess(out.index(ROOT_PROSE), out.index(SCENE_PROSE))

    def test_json_reports_the_nodes_and_totals(self) -> None:
        result = _run(self.project_dir, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["address"], "story/chapter-1/scene-2")
        self.assertEqual(data["narrative"], "story")
        self.assertEqual(data["operator"], "write")
        self.assertEqual([n["address"] for n in data["nodes"]][0], "story")
        self.assertEqual(data["totals"]["nodes"], 3)

    def test_an_address_argument_reports_a_different_spine(self) -> None:
        out = _strip_ansi(_run(self.project_dir, "/chapter-1").stdout)
        self.assertIn("Spine at story/chapter-1", out)
        self.assertIn(CHAPTER_PROSE, out)
        self.assertNotIn(SCENE_PROSE, out)

    def test_a_line_argument_is_reported_in_the_header(self) -> None:
        out = _strip_ansi(_run(self.project_dir, "/chapter-1/scene-2", "5").stdout)
        self.assertIn("as of line 5", out)
        self.assertIn("(cursor, truncated)", out)

    def test_outline_and_text_together_are_rejected(self) -> None:
        result = _run(self.project_dir, "--outline", "--text")
        self.assertEqual(result.returncode, 1)
        self.assertIn("mutually exclusive", _strip_ansi(result.stderr))

    def test_an_unknown_address_exits_nonzero_without_a_traceback(self) -> None:
        result = _run(self.project_dir, "/nope")
        self.assertEqual(result.returncode, 1)
        err = _strip_ansi(result.stderr)
        self.assertIn("lens spine:", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
