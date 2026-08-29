"""The `lens skill` command surface, run as a subprocess.

Two things here are contract rather than convenience. `lens skill` must print
*something* useful from anywhere — the command exists for an agent that has just
arrived and cannot be assumed to be standing in a working project — so it is the
one command outside the CLI preflight, and that is pinned. And `--check` must
exit non-zero on drift, because a checker whose exit code lies is worse than no
checker: CI and session-start hooks read nothing else.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

_SKILL_PATH = Path(".claude") / "skills" / "lens" / "SKILL.md"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


class _SkillCliCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="lens_skill_cli_")
        self.project_dir = Path(self.tmp)
        _git(self.project_dir, "init")
        _git(self.project_dir, "config", "user.email", "test@test.com")
        _git(self.project_dir, "config", "user.name", "Test")
        _git(self.project_dir, "config", "commit.gpgsign", "false")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_lens(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*_LENS_CMD, *args],
            cwd=cwd or self.project_dir,
            capture_output=True,
            text=True,
        )

    def init(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.run_lens("init", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.project_dir / "lens.toml").write_text(
            '[project]\ndatasets = ["testing"]\n', encoding="utf-8"
        )
        return result


class TestInitInstallsThePointer(_SkillCliCase):
    def test_init_installs_the_pointer_by_default(self) -> None:
        """Nobody remembers to opt in, so a new project is agent-ready or isn't."""
        self.init()

        self.assertTrue((self.project_dir / _SKILL_PATH).is_file())

    def test_init_no_skill_leaves_the_project_alone(self) -> None:
        result = self.run_lens("init", "--no-skill")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.project_dir / _SKILL_PATH).exists())


class TestSkillOutput(_SkillCliCase):
    def test_it_prints_the_bundled_invariants_and_the_live_project(self) -> None:
        self.init()

        result = self.run_lens("skill")

        self.assertEqual(result.returncode, 0, result.stderr)
        out = _strip_ansi(result.stdout)
        self.assertIn("tags.toml", out)
        self.assertIn("## This project", out)
        self.assertIn("testing", out)

    def test_it_prints_outside_a_project_instead_of_refusing(self) -> None:
        """The preflight every other command runs would make this useless."""
        empty = Path(tempfile.mkdtemp(prefix="lens_skill_bare_"))
        try:
            result = self.run_lens("skill", cwd=empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Working in a Lens project", result.stdout)
        self.assertIn("not inside a Lens project", result.stderr)

    def test_it_prints_before_lens_use_has_picked_a_narrative(self) -> None:
        """A fresh checkout has no active narrative, which is exactly when it is asked."""
        self.init()

        result = self.run_lens("skill")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("no active narrative", result.stderr)

    def test_sources_names_every_layer_and_where_it_came_from(self) -> None:
        self.init()
        skill_dir = self.project_dir / "skill"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text("## House rules\n\nAsk first.\n")

        result = self.run_lens("skill", "--sources")

        self.assertEqual(result.returncode, 0, result.stderr)
        labels = [line.split("\t")[0] for line in result.stdout.strip().split("\n")]
        self.assertEqual(labels, ["builtin", "generated", "dataset:testing", "project"])


class TestInstallAndCheck(_SkillCliCase):
    def test_check_exits_nonzero_when_the_pointer_is_missing(self) -> None:
        self.init("--no-skill")

        result = self.run_lens("skill", "--check")

        self.assertEqual(result.returncode, 1)
        self.assertIn("not installed", result.stdout)

    def test_check_exits_nonzero_when_the_pointer_has_drifted(self) -> None:
        self.init()
        path = self.project_dir / _SKILL_PATH
        path.write_text(path.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")

        result = self.run_lens("skill", "--check")

        self.assertEqual(result.returncode, 1)
        self.assertIn("stale", result.stdout)

    def test_install_then_check_passes(self) -> None:
        self.init("--no-skill")

        installed = self.run_lens("skill", "--install")
        self.assertEqual(installed.returncode, 0, installed.stderr)

        checked = self.run_lens("skill", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_install_stages_only_its_own_file(self) -> None:
        """A direct edit must never sweep somebody else's pending work into git."""
        self.init("--no-skill")
        _git(self.project_dir, "add", "-A")
        _git(self.project_dir, "commit", "-m", "base")
        (self.project_dir / "knowledge" / "scratch.md").write_text("pending\n")

        result = self.run_lens("skill", "--install")
        self.assertEqual(result.returncode, 0, result.stderr)

        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.project_dir, capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("A  .claude/skills/lens/SKILL.md", status)
        self.assertIn("?? knowledge/scratch.md", status)

    def test_install_and_check_together_is_an_error_not_a_silent_pick(self) -> None:
        self.init()

        result = self.run_lens("skill", "--install", "--check")

        self.assertEqual(result.returncode, 1)
        self.assertIn("not both", result.stderr)

    def test_install_outside_a_project_refuses_with_a_pointer_to_init(self) -> None:
        empty = Path(tempfile.mkdtemp(prefix="lens_skill_bare_"))
        try:
            result = self.run_lens("skill", "--install", cwd=empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("lens init", result.stderr)


class TestProjectCheckReportsDrift(_SkillCliCase):
    def test_lens_check_warns_but_does_not_fail_on_a_missing_pointer(self) -> None:
        """A lagging document is a stale document, not a broken project."""
        self.init("--no-skill")

        result = self.run_lens("check", "--skip-network")

        out = _strip_ansi(result.stdout)
        self.assertIn("[agent skill]", out)
        self.assertIn("warn", out.split("[agent skill]")[0].split("\n")[-1])


class TestCommandInventory(_SkillCliCase):
    """The command list is read off the running CLI, never described.

    That is the whole reason it is allowed to exist in a document whose thesis
    is that descriptions go stale: this one cannot, because it is the same
    object `--help` renders.
    """

    def test_the_listing_matches_what_help_would_print(self) -> None:
        self.init()

        skill = self.run_lens("skill")
        assert skill.returncode == 0, skill.stderr

        listing = _strip_ansi(skill.stdout)
        self.assertIn("### Commands available here", listing)
        for name in ("lens kb", "lens explain", "lens write", "lens skill"):
            self.assertIn(f"`{name}`", listing)

    def test_it_names_subcommands_so_an_agent_knows_they_exist(self) -> None:
        """`kb search` / `list` / `refs` are unreachable if nothing says they are there."""
        self.init()

        listing = _strip_ansi(self.run_lens("skill").stdout)

        kb_line = [ln for ln in listing.split("\n") if ln.startswith("  - `add`")]
        self.assertTrue(kb_line, listing)
        for sub in ("search", "list", "refs", "with-tag", "list-tags"):
            self.assertIn(f"`{sub}`", kb_line[0])

    def test_dataset_gating_is_reflected_not_described(self) -> None:
        """`play` exists only with the rpg dataset, and the listing follows."""
        self.init()
        listing_without = _strip_ansi(self.run_lens("skill").stdout)
        self.assertNotIn("`lens play`", listing_without)

        (self.project_dir / "lens.toml").write_text(
            '[project]\ndatasets = ["rpg"]\n', encoding="utf-8"
        )
        listing_with = _strip_ansi(self.run_lens("skill").stdout)

        self.assertIn("`lens play`", listing_with)

    def test_kb_group_help_names_the_discovery_commands(self) -> None:
        """`lens kb --help` is where somebody looks first; it must not lag."""
        self.init()

        out = _strip_ansi(self.run_lens("kb", "--help").stdout)
        # Rich wraps, so collapse whitespace before matching.
        flat = " ".join(out.split())
        for sub in ("search", "list", "refs", "with-tag"):
            self.assertIn(sub, flat)

    def test_top_level_help_points_a_newcomer_at_lens_skill(self) -> None:
        self.init()

        flat = " ".join(_strip_ansi(self.run_lens("--help").stdout).split())

        self.assertIn("lens skill", flat)

    def test_help_panels_print_in_a_fixed_reading_order(self) -> None:
        """Rich orders panels by registration; that made it an accident."""
        self.init()
        (self.project_dir / "lens.toml").write_text(
            '[project]\ndatasets = ["rpg"]\n', encoding="utf-8"
        )

        out = _strip_ansi(self.run_lens("--help").stdout)
        seen = [
            name
            for name in ("Project", "Operators", "Knowledge", "Serving & deploy")
            if name in out
        ]
        positions = [out.index(name) for name in seen]

        self.assertEqual(seen, ["Project", "Operators", "Knowledge", "Serving & deploy"])
        self.assertEqual(positions, sorted(positions))
