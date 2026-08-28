"""Output shape of ``lens kb search`` / ``list`` / ``refs``.

The core tests own the semantics; these own the text, because the text *is* the
interface here. ``id:line:text`` is a contract — an agent pipes it into `cut`,
`sort`, and `xargs lens kb get` — so the separators, the ``0`` on identity
matches and the grep-style context prefixes are pinned rather than left to
whatever the renderer happens to do.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class _KbCliCase(unittest.TestCase):
    project_dir: Path
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        from lens.core.knowledge import KnowledgeStore
        from lens.testing.project import setup_test_project

        cls.tmp = tempfile.mkdtemp(prefix="lens_kb_discovery_cli_")
        cls.project_dir = Path(cls.tmp)
        setup_test_project(cls.project_dir, "http://127.0.0.1:1/v1", opening_write=False)
        store = KnowledgeStore.for_project(cls.project_dir)
        store.store_object(
            "person.rowan",
            "ROWAN\nA ranger.\n\nShe grapples the guard.\nShe grapples again.\n",
        )
        store.add_tags("person.rowan", ["pc"])
        KnowledgeStore.clear_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_kb(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*_LENS_CMD, "kb", *args],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )

    def lines(self, *args: str) -> list[str]:
        result = self.run_kb(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return _strip_ansi(result.stdout).rstrip("\n").split("\n")


class TestSearchOutput(_KbCliCase):
    def test_a_body_match_prints_id_line_text(self) -> None:
        lines = self.lines("search", "grapples the guard")

        self.assertEqual(lines, ["person.rowan:4:She grapples the guard."])

    def test_an_identity_match_prints_line_zero_and_the_field(self) -> None:
        lines = self.lines("search", "rowan", "-t", "person")

        self.assertEqual(lines, ["person.rowan:0:[id] person.rowan"])

    def test_context_lines_use_grep_dashes_and_never_repeat(self) -> None:
        lines = self.lines("search", "grapples", "-C", "2", "-t", "person")

        self.assertEqual(
            lines,
            [
                "person.rowan-2-A ranger.",
                "person.rowan-3-",
                "person.rowan:4:She grapples the guard.",
                "person.rowan:5:She grapples again.",
                "person.rowan-6-",
            ],
        )

    def test_ids_only_prints_bare_ids(self) -> None:
        lines = self.lines("search", "grapples", "-l")

        self.assertEqual(lines, ["person.rowan"])

    def test_headline_adds_a_listing_header_above_the_hits(self) -> None:
        lines = self.lines("search", "grapples the guard", "--headline")

        self.assertEqual(lines[0], "person.rowan  [pc]  SOURCE=project")
        self.assertEqual(lines[1], "    ROWAN")
        self.assertEqual(lines[-1], "person.rowan:4:She grapples the guard.")

    def test_json_carries_the_matches(self) -> None:
        result = self.run_kb("search", "grapples the guard", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["matches"][0]["line"], 4)

    def test_a_bad_source_filter_is_an_error_not_a_silent_default(self) -> None:
        result = self.run_kb("search", "x", "--source", "everywhere")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--source", result.stderr)

    def test_an_invalid_regex_exits_nonzero_with_a_message(self) -> None:
        result = self.run_kb("search", "[unclosed")

        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid pattern", result.stderr)

    def test_no_match_is_a_quiet_success(self) -> None:
        result = self.run_kb("search", "no-such-text-anywhere")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestListOutput(_KbCliCase):
    def test_it_prints_the_shared_listing_shape(self) -> None:
        lines = self.lines("list", "-t", "person")

        self.assertIn("person.rowan  [pc]  SOURCE=project", lines)
        self.assertIn("    ROWAN", lines)

    def test_ids_only_prints_bare_ids(self) -> None:
        lines = self.lines("list", "-t", "person", "-l")

        self.assertTrue(all(re.fullmatch(r"person\.[\w.-]+", line) for line in lines))

    def test_json_carries_ids_and_items(self) -> None:
        result = self.run_kb("list", "-t", "person", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = json.loads(result.stdout)
        self.assertIn("person.rowan", payload["ids"])


class TestRefsOutput(_KbCliCase):
    def test_it_groups_the_two_directions_under_headers(self) -> None:
        lines = self.lines("refs", "person.rowan")

        self.assertEqual(lines[0], "person.rowan  [pc]  SOURCE=project")
        self.assertIn("OUT", lines)

    def test_out_only_omits_the_inbound_group(self) -> None:
        lines = self.lines("refs", "person.rowan", "--out")

        self.assertNotIn("IN", lines)

    def test_an_unknown_id_says_so_and_still_exits_zero(self) -> None:
        result = self.run_kb("refs", "person.nobody")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no such object", result.stdout)

    def test_json_names_the_direction_of_each_edge(self) -> None:
        result = self.run_kb("refs", "person.rowan", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload["id"], "person.rowan")
        self.assertTrue(
            all(ref["direction"] in ("out", "in") for ref in payload["refs"])
        )


if __name__ == "__main__":
    unittest.main()
