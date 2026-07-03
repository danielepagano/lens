"""E2E tests for ``[[dataset_repo]]`` clone + fast-forward via ``execute_refresh``.

Tests the Phase 7 cloud-deployed refresh flow without needing a server or
fake LLM — just git and the core Python API.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from lens.core.commands.refresh import execute_refresh
from lens.core.project import ProjectSession


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


class TestCloudDatasetRepoRefresh:
    """Clone + fast-forward of ``[[dataset_repo]]`` under ``LENS_CLOUD_DEPLOYED=1``."""

    def test_clone_and_fast_forward(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo_name = "test-ds"

        # 1. Create a bare dataset repo with initial content
        bare_dir = tmp_path / "bare" / f"{repo_name}.git"
        bare_dir.mkdir(parents=True)
        _git("init", "--bare", str(bare_dir), cwd=tmp_path)

        work_dir = tmp_path / "work"
        _git("clone", str(bare_dir), str(work_dir), cwd=tmp_path)
        (work_dir / "data.txt").write_text("initial\n")
        _git("add", "data.txt", cwd=work_dir)
        _git(
            "-c", "user.name=Test", "-c", "user.email=test@test.com",
            "commit", "-m", "initial",
            cwd=work_dir,
        )
        _git("push", cwd=work_dir)

        # 2. Create a Lens project with [[dataset_repo]]
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "lens.toml").write_text(
            f'[[dataset_repo]]\nname = "{repo_name}"\ngit_url = "{bare_dir}"\nref = "main"\n'
        )

        # 3. Init git in project dir with a remote so refresh doesn't error
        _git("init", cwd=project_dir)
        proj_bare = tmp_path / "proj-bare.git"
        _git("init", "--bare", str(proj_bare), cwd=tmp_path)
        _git("remote", "add", "origin", str(proj_bare), cwd=project_dir)
        _git(
            "-c", "user.name=Test", "-c", "user.email=test@test.com",
            "commit", "--allow-empty", "-m", "init",
            cwd=project_dir,
        )
        _git("push", "--set-upstream", "origin", "main", cwd=project_dir)

        # 4. Enable cloud mode
        cloud_base = tmp_path / "cloud"
        cloud_base.mkdir(parents=True)
        monkeypatch.setenv("LENS_CLOUD_DEPLOYED", "1")
        monkeypatch.setenv("LENS_PROJECT_DIR", str(cloud_base))

        session = ProjectSession(project_dir, project_dir)

        # 5. First refresh → should clone the dataset repo
        result = execute_refresh(session)

        ds_entries = [e for e in result.entries if e.name == repo_name]
        assert len(ds_entries) == 1, (
            f"Expected one entry for {repo_name}, got {result.entries}"
        )
        e = ds_entries[0]
        assert e.status == "ok", f"Expected ok, got {e}"
        assert e.action == "cloned", f"Expected cloned, got {e}"

        clone_dir = cloud_base / "_datasets" / repo_name
        assert clone_dir.is_dir()
        assert (clone_dir / "data.txt").read_text() == "initial\n"

        # 6. Push a new commit to the dataset repo
        (work_dir / "data.txt").write_text("initial\nupdated\n")
        _git("add", "data.txt", cwd=work_dir)
        _git(
            "-c", "user.name=Test", "-c", "user.email=test@test.com",
            "commit", "-m", "update data",
            cwd=work_dir,
        )
        _git("push", cwd=work_dir)

        # 7. Second refresh → should fast-forward
        result2 = execute_refresh(session)
        ds_entries2 = [e for e in result2.entries if e.name == repo_name]
        assert len(ds_entries2) == 1
        assert ds_entries2[0].status == "ok"
        assert ds_entries2[0].action == "fast_forwarded"

        assert (clone_dir / "data.txt").read_text() == "initial\nupdated\n"
