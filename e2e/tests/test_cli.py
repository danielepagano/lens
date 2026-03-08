"""CLI integration tests run against a live test project.

These tests invoke the ``lens`` CLI as a subprocess, exactly as a user (or
LLM) would, against a temp project with the ``dnd`` dataset enabled and a
fake LLM.  They exercise stats output, dataset KB lookups, and the write
operator end-to-end.

Running::

    poe test-e2e
    # or just this file:
    pytest e2e/tests/test_cli.py -n 0 -v
"""

from __future__ import annotations

import io
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
# Module-scoped fixture: project with dnd dataset
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dnd_llm() -> Generator[FakeLLMServer, None, None]:
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def dnd_project(dnd_llm: FakeLLMServer) -> Generator[Path, None, None]:
    """A Lens project with the ``dnd`` dataset enabled and a fake LLM."""
    import tomllib
    import tomli_w

    tmp = tempfile.mkdtemp(prefix="lens_cli_test_")
    project_dir = Path(tmp)

    # Create the base project (uses "testing" dataset, with content).
    setup_test_project(project_dir, dnd_llm.base_url)

    # Swap the dataset from "testing" to "dnd".
    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    if isinstance(cfg.get("project"), dict):
        cfg["project"]["datasets"] = ["dnd"]
    with io.BytesIO() as buf:
        tomli_w.dump(cfg, buf)
        lens_toml.write_bytes(buf.getvalue())

    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestCliStats:
    def test_stats_exits_zero(self, dnd_project: Path) -> None:
        r = _lens("stats", cwd=dnd_project)
        assert r.returncode == 0, r.stderr

    def test_stats_shows_narrative(self, dnd_project: Path) -> None:
        r = _lens("stats", cwd=dnd_project)
        # Active narrative is "story".
        assert "story" in r.stdout

    def test_stats_shows_kb_objects(self, dnd_project: Path) -> None:
        r = _lens("stats", cwd=dnd_project)
        # dnd dataset has many objects; project-local ones (person.amy,
        # place.forest) are also present.  At minimum 2 local objects.
        assert "Knowledge Store" in r.stdout
        assert "Objects:" in r.stdout

    def test_stats_shows_cursor(self, dnd_project: Path) -> None:
        r = _lens("stats", cwd=dnd_project)
        assert "Active narrative cursor:" in r.stdout


# ---------------------------------------------------------------------------
# KB lookups against the dnd dataset
# ---------------------------------------------------------------------------


class TestCliKbDnd:
    def test_kb_get_rules_dnd(self, dnd_project: Path) -> None:
        """Lookup rules.dnd — only exists in the dnd dataset."""
        r = _lens("kb", "get", "rules.dnd", cwd=dnd_project)
        assert r.returncode == 0, r.stderr
        # The rules file contains D&D 2024 reference content.
        assert r.stdout.strip(), "expected non-empty output for rules.dnd"
        assert "D&D" in r.stdout or "d20" in r.stdout.lower()

    def test_kb_get_rules_engagement(self, dnd_project: Path) -> None:
        """Lookup rules.engagement — only exists in the dnd dataset."""
        r = _lens("kb", "get", "rules.engagement", cwd=dnd_project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected non-empty output for rules.engagement"

    def test_kb_with_tag_finds_dnd_objects(self, dnd_project: Path) -> None:
        """kb with-tag against a dnd tag should return results from the dataset."""
        # "level:0" tags cantrips in the dnd dataset.
        r = _lens("kb", "with-tag", "level:0", cwd=dnd_project)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip(), "expected spell objects tagged level:0 from dnd dataset"

    def test_kb_get_local_object(self, dnd_project: Path) -> None:
        """person.amy was created during project setup — must still be accessible."""
        r = _lens("kb", "get", "person.amy", cwd=dnd_project)
        assert r.returncode == 0, r.stderr
        assert "Amy" in r.stdout

    def test_kb_get_missing_object_returns_empty(self, dnd_project: Path) -> None:
        """Fetching a non-existent ID is not an error; it just prints nothing."""
        r = _lens("kb", "get", "person.nobody", cwd=dnd_project)
        assert r.returncode == 0
        assert r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Write operator via CLI
# ---------------------------------------------------------------------------


class TestCliWrite:
    def test_write_exits_zero(self, dnd_project: Path) -> None:
        # Prompt is a positional argument, not --prompt.
        r = _lens("write", "continue the adventure", "--llm", "mock", cwd=dnd_project)
        assert r.returncode == 0, r.stderr

    def test_write_adds_content(self, dnd_project: Path) -> None:
        """After write, at least one narrative node file contains Lorem Ipsum."""
        _lens("write", "describe the scene", "--llm", "mock", cwd=dnd_project)
        node_files = list((dnd_project / "narrative" / "story").rglob("*.md"))
        assert node_files, "expected narrative node files to exist"
        all_content = "\n".join(f.read_text() for f in node_files)
        assert "Lorem ipsum" in all_content

    def test_write_opens_transaction(self, dnd_project: Path) -> None:
        """write leaves an open transaction (unstaged changes)."""
        _lens("write", "one more beat", "--llm", "mock", cwd=dnd_project)
        stats = _lens("stats", cwd=dnd_project)
        # stats prints "Open transaction:         yes"
        assert "Open transaction:         yes" in stats.stdout
