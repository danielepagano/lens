"""Tests for the ``lens explain`` CLI adapter."""

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


def _run(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_LENS_CMD, "explain", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )


class TestExplainCli(unittest.TestCase):
    project_dir: Path
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        from lens.testing.project import setup_test_project

        cls.tmp = tempfile.mkdtemp(prefix="lens_explain_cli_")
        cls.project_dir = Path(cls.tmp)
        session = setup_test_project(
            cls.project_dir, "http://127.0.0.1:1/v1", opening_write=False
        )
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        cursor.md_path().write_text(
            cursor.md_path().read_text(encoding="utf-8") + "\nAmy entered the wood.\n",
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_table_lists_blocks_and_a_total(self) -> None:
        result = _run(self.project_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = _strip_ansi(result.stdout)
        self.assertIn("RELEVANT KNOWLEDGE", out)
        self.assertIn("kb:person.amy", out)
        self.assertIn("TOTAL", out)

    def test_default_table_omits_framing_noise(self) -> None:
        out = _strip_ansi(_run(self.project_dir).stdout)
        self.assertNotIn("(block framing)", out)
        self.assertNotIn("(message separators)", out)

    def test_verbose_shows_framing_with_real_token_counts(self) -> None:
        out = _strip_ansi(_run(self.project_dir, "-v").stdout)
        framing = next(
            line for line in out.splitlines() if "(block framing)" in line
        )
        # The wrapper costs tokens; the column must not report a bare zero.
        tokens = int(framing.split()[2].replace(",", ""))
        self.assertGreater(tokens, 0)

    def test_verbose_columns_sum_to_the_printed_total(self) -> None:
        """The point of -v is that a reader can add the rows up by hand."""
        out = _strip_ansi(_run(self.project_dir, "-v").stdout)
        tokens = 0
        size = 0
        total_tokens = total_bytes = -1
        for line in out.splitlines():
            match = re.search(r"([\d,]+)\s+([\d,]+)\s+([\d.]+)%", line)
            if match is None:
                continue
            row_tokens = int(match.group(1).replace(",", ""))
            row_bytes = int(match.group(2).replace(",", ""))
            if line.startswith("TOTAL"):
                total_tokens, total_bytes = row_tokens, row_bytes
            elif line.startswith("  ") or line.startswith("(message"):
                tokens += row_tokens
                size += row_bytes
        self.assertEqual(tokens, total_tokens)
        self.assertEqual(size, total_bytes)

    def test_verbose_prints_the_cache_note(self) -> None:
        out = _strip_ansi(_run(self.project_dir, "-v").stdout)
        self.assertIn("heuristic", out)

    def test_json_output_is_parseable(self) -> None:
        result = _run(self.project_dir, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["operator"], "write")
        self.assertGreater(payload["totals"]["bytes"], 0)

    def test_operator_option_changes_the_report(self) -> None:
        result = _run(self.project_dir, "--operator", "section", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["operator"], "section")

    def test_unknown_operator_exits_nonzero(self) -> None:
        result = _run(self.project_dir, "--operator", "not-real")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown operator", _strip_ansi(result.stderr))

    def test_line_argument_is_reported(self) -> None:
        result = _run(self.project_dir, "/", "2", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["line"], 2)

    def test_leaves_the_repo_clean(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        ).stdout
        _run(self.project_dir)
        after = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(before, after)



class TestExplainAddressing(unittest.TestCase):
    """Several narrative trees, one active — where '/' semantics bite."""

    project_dir: Path
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        import os

        from lens.core.commands.use import use_narrative
        from lens.testing.project import setup_test_project

        cls.tmp = tempfile.mkdtemp(prefix="lens_explain_addr_")
        cls.project_dir = Path(cls.tmp)
        setup_test_project(
            cls.project_dir,
            "http://127.0.0.1:1/v1",
            narrative_name="Act-1",
            opening_write=False,
        )
        cwd = Path.cwd()
        os.chdir(cls.project_dir)
        try:
            use_narrative("Design")
            use_narrative("Act-1")
        finally:
            os.chdir(cwd)
        walstein = cls.project_dir / "narrative" / "Act-1" / "Walstein"
        walstein.mkdir(parents=True)
        (walstein / "_node.md").write_text("# Walstein\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_slash_addresses_the_active_narrative_root(self) -> None:
        result = _run(self.project_dir, "/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Context at Act-1", _strip_ansi(result.stdout))

    def test_bare_narrative_name_addresses_that_tree(self) -> None:
        result = _run(self.project_dir, "Design")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Context at Design", _strip_ansi(result.stdout))

    def test_key_under_the_active_narrative_resolves(self) -> None:
        result = _run(self.project_dir, "/Walstein")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Context at Act-1/Walstein", _strip_ansi(result.stdout))

    def test_trailing_slash_is_accepted(self) -> None:
        """Tab-completing a directory produces one; it must not be an error."""
        result = _run(self.project_dir, "/Walstein/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Context at Act-1/Walstein", _strip_ansi(result.stdout))

    def test_narrative_name_after_slash_suggests_a_working_address(self) -> None:
        result = _run(self.project_dir, "/Act-1/Walstein")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did you mean '/Walstein'?", _strip_ansi(result.stderr))

    def test_the_suggested_address_actually_works(self) -> None:
        """A suggestion that does not resolve would be worse than none."""
        stderr = _strip_ansi(_run(self.project_dir, "/Act-1/Walstein").stderr)
        suggested = re.search(r"did you mean '([^']+)'", stderr)
        assert suggested is not None
        retry = _run(self.project_dir, suggested.group(1))
        self.assertEqual(retry.returncode, 0, retry.stderr)


if __name__ == "__main__":
    unittest.main()
