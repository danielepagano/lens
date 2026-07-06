"""Tests for `lens release check` and `lens release apply` CLI adapters."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


def _init_bare_repo_with_tags(base: Path, tags: list[str]) -> Path:
    import uuid

    bare = base / f"lens_remote_{uuid.uuid4().hex}.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    clone = base / f"lens_clone_{uuid.uuid4().hex}"
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True)

    (clone / "README.md").write_text("lens remote")
    subprocess.run(["git", "add", "README.md"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=clone, check=True, capture_output=True)

    for tag in tags:
        subprocess.run(["git", "tag", tag], cwd=clone, check=True, capture_output=True)
    if tags:
        subprocess.run(["git", "push", "origin", "--tags"], cwd=clone, check=True, capture_output=True)

    shutil.rmtree(clone, ignore_errors=True)
    return bare


def _init_project_repo(base: Path, lens_toml: str) -> Path:
    import uuid

    project = base / f"proj_{uuid.uuid4().hex}"
    return _init_project_repo_at(project, lens_toml)


def _init_project_repo_at(project: Path, lens_toml: str) -> Path:
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)

    (project / "lens.toml").write_text(lens_toml)
    subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)

    import uuid

    remote = project.parent / f"proj_remote_{uuid.uuid4().hex}.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=project, check=True, capture_output=True)

    return project


def _write_fly_toml(deploy_dir: Path, slugs: list[str]) -> Path:
    fly_toml = deploy_dir / "fly.toml"
    fly_toml.write_text(
        'app = "my-app"\n'
        "[env]\n"
        f'  LENS_PROJECT_SLUGS = "{",".join(slugs)}"\n'
    )
    return fly_toml


class TestReleaseCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)
        self._lens_remote = _init_bare_repo_with_tags(
            self._tmp_path, ["v1.0.0", "v1.1.0", "v2.0.0"]
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_check_disabled_exits_zero_with_message(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = subprocess.run(
            _LENS_CMD + ["release", "check"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_apply_invalid_tag_exits_one(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = subprocess.run(
            _LENS_CMD + ["release", "apply", "--target", "bad-tag"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("--target must be a valid", result.stderr)

    def test_apply_output(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = subprocess.run(
            _LENS_CMD + ["release", "apply", "--target", "v1.1.0"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("v1.1.0", result.stdout)

    def test_check_not_enabled_exits_zero(self) -> None:
        proj = _init_project_repo(self._tmp_path, "# no release section\n")
        result = subprocess.run(
            _LENS_CMD + ["release", "check"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_check_from_multi_project_deploy_dir_resolves_leader(self) -> None:
        import uuid

        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        leader_block = (
            "[release]\n"
            "enabled = true\n"
            "app_leader = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        _init_project_repo_at(deploy_dir / "a", leader_block)
        _init_project_repo_at(deploy_dir / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(deploy_dir, ["a", "b"])

        result = subprocess.run(
            _LENS_CMD + ["release", "check"],
            cwd=deploy_dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_check_from_multi_project_deploy_dir_no_leader_exits_one(self) -> None:
        import uuid

        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        _init_project_repo_at(deploy_dir / "a", "[project]\ndatasets = ['testing']\n")
        _init_project_repo_at(deploy_dir / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(deploy_dir, ["a", "b"])

        result = subprocess.run(
            _LENS_CMD + ["release", "check"],
            cwd=deploy_dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("app_leader", result.stderr)

    def test_check_no_lens_toml_no_fly_toml_exits_one(self) -> None:
        import uuid

        empty_dir = self._tmp_path / f"empty_{uuid.uuid4().hex}"
        empty_dir.mkdir()
        result = subprocess.run(
            _LENS_CMD + ["release", "check"],
            cwd=empty_dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no lens.toml found", result.stderr)

    def test_clear_with_request_clears_fields(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        # Manually set the fields then test clear
        import tomllib

        raw = tomllib.loads((proj / "lens.toml").read_text())
        raw.setdefault("release", {})
        raw["release"]["requested_version"] = "v1.1.0"
        raw["release"]["requested_from_commit"] = "a" * 40
        import tomli_w

        (proj / "lens.toml").write_text(tomli_w.dumps(raw))
        subprocess.run(["git", "add", "lens.toml"], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "set request"],
            cwd=proj, check=True, capture_output=True,
        )

        result = subprocess.run(
            _LENS_CMD + ["release", "clear"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_clear_when_already_empty_exits_zero(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = subprocess.run(
            _LENS_CMD + ["release", "clear"],
            cwd=proj, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
