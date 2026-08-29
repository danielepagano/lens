"""CLI integration tests run against a live test project.

These tests invoke the ``lens`` CLI as a subprocess, exactly as a user (or
LLM) would, against a temp project with ``rpg`` and ``testing`` datasets
enabled and a fake LLM.  They exercise stats output, dataset KB lookups
(including later-dataset shadowing), and the write operator end-to-end.

Running::

    poe test-e2e
    # or just this file:
    pytest e2e/tests/test_cli.py -n 0 -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

_LENS = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


def _lens(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_LENS, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Module-scoped fixture: project with rpg + testing datasets
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cli_llm() -> Generator[FakeLLMServer, None, None]:
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def cli_project(cli_llm: FakeLLMServer) -> Generator[Path, None, None]:
    """A Lens project with ``rpg`` and ``testing`` datasets and a fake LLM."""
    tmp = tempfile.mkdtemp(prefix="lens_cli_test_")
    project_dir = Path(tmp)
    setup_test_project(
        project_dir, cli_llm.base_url, datasets=["rpg", "testing"]
    )
    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestCliStats:
    def test_stats_exits_zero(self, cli_project: Path) -> None:
        r = _lens("stats", cwd=cli_project)
        assert r.returncode == 0, r.stderr

    def test_stats_shows_narrative(self, cli_project: Path) -> None:
        r = _lens("stats", cwd=cli_project)
        # Active narrative is "story".
        assert "story" in r.stdout

    def test_stats_shows_kb_objects(self, cli_project: Path) -> None:
        r = _lens("stats", cwd=cli_project)
        # Bundled testing dataset plus project-local objects (person.amy,
        # place.forest).
        assert "Knowledge Store" in r.stdout
        assert "Objects:" in r.stdout

    def test_stats_shows_cursor(self, cli_project: Path) -> None:
        r = _lens("stats", cwd=cli_project)
        assert "Active narrative cursor:" in r.stdout


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


class TestCliExplain:
    def test_explain_reports_blocks_and_a_total(self, cli_project: Path) -> None:
        r = _lens("explain", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        assert "RELEVANT KNOWLEDGE" in r.stdout
        assert "kb:person.amy" in r.stdout
        assert "TOTAL" in r.stdout

    def test_explain_json_totals_add_up(self, cli_project: Path) -> None:
        import json

        r = _lens("explain", "--json", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        totals = json.loads(r.stdout)["totals"]
        assert totals["bytes"] == totals["accounted_bytes"] + totals["other_bytes"]

    def test_explain_as_play_uses_rpg_pins_and_modalities(
        self, cli_project: Path
    ) -> None:
        import json

        r = _lens("explain", "--operator", "play", "--json", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["operator"] == "play"
        assert "rpg_play_context" in data["active_modalities"]

    def test_explain_does_not_dirty_the_repo(self, cli_project: Path) -> None:
        def status() -> str:
            return subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cli_project,
                capture_output=True,
                text=True,
            ).stdout

        before = status()
        _lens("explain", cwd=cli_project)
        assert status() == before


# ---------------------------------------------------------------------------
# KB lookups against bundled rpg + testing datasets
# ---------------------------------------------------------------------------


class TestCliKbBundled:
    def test_kb_get_rules_system(self, cli_project: Path) -> None:
        """Lookup rules.system — testing dataset shadows rpg when listed second."""
        r = _lens("kb", "get", "rules.system", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected non-empty output for rules.system"
        assert "TESTING_RULES_SYSTEM_SHADOW" in r.stdout

    def test_kb_get_rules_rpg(self, cli_project: Path) -> None:
        """Lookup rules.rpg from the rpg dataset."""
        r = _lens("kb", "get", "rules.rpg", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected non-empty output for rules.rpg"

    def test_kb_with_tag_finds_dataset_objects(self, cli_project: Path) -> None:
        """kb with-tag returns IDs from the testing dataset tag index."""
        r = _lens("kb", "with-tag", "protagonist", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected objects tagged protagonist"
        assert "person.hero" in r.stdout

    def test_kb_get_local_object(self, cli_project: Path) -> None:
        """person.amy was created during project setup — must still be accessible."""
        r = _lens("kb", "get", "person.amy", cwd=cli_project)
        assert r.returncode == 0, r.stderr
        assert "Amy" in r.stdout

    def test_kb_get_missing_object_returns_empty(self, cli_project: Path) -> None:
        """Fetching a non-existent ID is not an error; it just prints nothing."""
        r = _lens("kb", "get", "person.nobody", cwd=cli_project)
        assert r.returncode == 0
        assert r.stdout.strip() == ""

    def test_kb_get_facet_expand(self, cli_project: Path) -> None:
        """``--facet-expand`` adds the `-` facets that design/advance see."""
        r = _lens("kb", "add", "person.amy-prep", "Amy prep material.", cwd=cli_project)
        assert r.returncode == 0, r.stderr

        plain = _lens("kb", "get", "person.amy", cwd=cli_project)
        assert plain.returncode == 0, plain.stderr
        assert "Amy prep material." not in plain.stdout

        expanded = _lens("kb", "get", "person.amy", "--facet-expand", cwd=cli_project)
        assert expanded.returncode == 0, expanded.stderr
        assert "Amy prep material." in expanded.stdout


# ---------------------------------------------------------------------------
# Write operator via CLI
# ---------------------------------------------------------------------------


class TestCliWrite:
    def test_write_exits_zero(self, cli_project: Path) -> None:
        # Prompt is a positional argument, not --prompt.
        r = _lens("write", "continue the adventure", "--llm", "mock", cwd=cli_project)
        assert r.returncode == 0, r.stderr

    def test_write_adds_content(self, cli_project: Path) -> None:
        """After write, at least one narrative node file contains Lorem Ipsum."""
        _lens("write", "describe the scene", "--llm", "mock", cwd=cli_project)
        node_files = list((cli_project / "narrative" / "story").rglob("*.md"))
        assert node_files, "expected narrative node files to exist"
        all_content = "\n".join(f.read_text() for f in node_files)
        assert "Lorem ipsum" in all_content

    def test_write_opens_transaction(self, cli_project: Path) -> None:
        """write leaves an open transaction (unstaged changes)."""
        _lens("write", "one more beat", "--llm", "mock", cwd=cli_project)
        stats = _lens("stats", cwd=cli_project)
        # stats prints "Open transaction: yes"
        assert "Open transaction: yes" in stats.stdout


# ---------------------------------------------------------------------------
# Agent onboarding
# ---------------------------------------------------------------------------


class TestCliSkill:
    """`lens skill` against a real project, which is the only place it is true.

    The unit tests build their own projects; this one runs against the same
    `setup_test_project` shape everything else here uses, so what an agent
    checking out a Lens project would actually read is what is asserted.
    """

    def test_setup_installs_the_pointer_and_it_is_current(self, cli_project: Path) -> None:
        pointer = cli_project / ".claude" / "skills" / "lens" / "SKILL.md"
        assert pointer.is_file()

        r = _lens("skill", "--check", cwd=cli_project)
        assert r.returncode == 0, r.stdout

    def test_it_reports_the_datasets_that_resolve_outside_the_checkout(
        self, cli_project: Path
    ) -> None:
        r = _lens("skill", cwd=cli_project)
        assert r.returncode == 0, r.stderr

        assert "## This project" in r.stdout
        assert "`rpg`" in r.stdout
        assert "`testing`" in r.stdout
        # The rpg dataset ships its own conventions layer.
        assert "Conventions of the `rpg` dataset" in r.stdout

    def test_it_lists_the_design_modules_and_requestable_modules(
        self, cli_project: Path
    ) -> None:
        r = _lens("skill", cwd=cli_project)

        assert "### Design modules" in r.stdout
        assert "rules.skirmish" in r.stdout

    def test_it_does_not_leak_the_guidance_into_the_committed_pointer(
        self, cli_project: Path
    ) -> None:
        """The pointer is compared byte for byte; project facts would break that."""
        pointer = (cli_project / ".claude" / "skills" / "lens" / "SKILL.md").read_text()

        assert "## This project" not in pointer
        assert "rules.skirmish" not in pointer
