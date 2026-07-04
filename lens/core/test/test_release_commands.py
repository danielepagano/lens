"""Tests for the release decision engine commands.

All tests that involve parent-hash matching create real git commits in
temporary repositories so that ``git rev-list`` and related commands work.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from lens.core.commands.release import (
    execute_release_apply,
    execute_release_check,
    resolve_release_project_root,
)
from lens.core.exceptions import LensException


def _init_bare_repo_with_tags(base: Path, tags: list[str]) -> Path:
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

    remote = project.parent / f"proj_remote_{uuid.uuid4().hex}.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=project, check=True, capture_output=True)

    return project


def _get_head_sha(project: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _make_commit(project: Path, file_content: str) -> str:
    """Create a new commit on the project repo and return its SHA."""
    marker = project / f"marker_{uuid.uuid4().hex}.txt"
    marker.write_text(file_content)
    subprocess.run(["git", "add", str(marker)], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", file_content],
        cwd=project, check=True, capture_output=True,
    )
    return _get_head_sha(project)


def _write_fly_toml(deploy_dir: Path, slugs: list[str]) -> Path:
    fly_toml = deploy_dir / "fly.toml"
    fly_toml.write_text(
        'app = "my-app"\n'
        "[env]\n"
        f'  LENS_PROJECT_SLUGS = "{",".join(slugs)}"\n'
    )
    return fly_toml


class TestReleaseCommands(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)
        self._lens_remote = _init_bare_repo_with_tags(
            self._tmp_path, ["v1.0.0", "v1.1.0", "v2.0.0"]
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- check: enabled / disabled ----

    def test_check_disabled_returns_none(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_check_enabled_no_request_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    # ---- check: parent matching ----

    def test_check_parent_matches_returns_apply(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        before = _get_head_sha(proj)

        # Set requested_version + requested_from_commit, then commit (child of before)
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            f"requested_version = \"v1.1.0\"\n"
            f"requested_from_commit = \"{before}\"\n"
        )
        (proj / "lens.toml").write_text(block)
        subprocess.run(["git", "add", "lens.toml"], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "set requested version"],
            cwd=proj, check=True, capture_output=True,
        )

        # The committed change has `before` as its parent → match
        result = execute_release_check(proj, since=before)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v1.1.0")

    def test_check_parent_does_not_match_returns_none(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        irrelevant = "0" * 40

        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.1.0\"\n"
            f"requested_from_commit = \"{irrelevant}\"\n"
        )
        (proj / "lens.toml").write_text(block)
        subprocess.run(["git", "add", "lens.toml"], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "set requested version"],
            cwd=proj, check=True, capture_output=True,
        )
        after_sha = _get_head_sha(proj)

        result = execute_release_check(proj, since=after_sha)
        self.assertEqual(result.action, "none")

    def test_check_with_since_range_multi_commit(self) -> None:
        """A push carrying two commits: only the first has
        requested_from_commit as its parent."""
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        before = _get_head_sha(proj)

        # First commit after before becomes the child of before
        _make_commit(proj, "first post-init")

        # Set requested_from_commit = before
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            f"requested_version = \"v1.1.0\"\n"
            f"requested_from_commit = \"{before}\"\n"
        )
        (proj / "lens.toml").write_text(block)
        subprocess.run(["git", "add", "lens.toml"], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "set requested version"],
            cwd=proj, check=True, capture_output=True,
        )
        # Check the range before..HEAD — the first commit's parent is before (match)
        result = execute_release_check(proj, since=before)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v1.1.0")

    def test_check_unparseable_tag_raises(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"not-a-valid-version\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with self.assertRaises(LensException):
            execute_release_check(proj)

    def test_check_empty_requested_from_commit_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.1.0\"\n"
            "requested_from_commit = \"\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    # ---- apply ----

    def test_apply_disabled_raises(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        with self.assertRaises(LensException):
            execute_release_apply(proj, "v1.0.0")

    def test_apply_empty_repo_url_raises(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            "lens_repo_url = \"\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with self.assertRaises(LensException):
            execute_release_apply(proj, "v1.0.0")

    def test_apply_invalid_tag_raises(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with self.assertRaises(LensException):
            execute_release_apply(proj, "not-a-tag")

    def test_apply_never_commits(self) -> None:
        """Assert execute_release_apply never touches git — no commit, no push."""
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        before = _get_head_sha(proj)
        result = execute_release_apply(proj, "v1.1.0")
        self.assertEqual(result.tag, "v1.1.0")
        after = _get_head_sha(proj)
        self.assertEqual(before, after, "apply should not create a commit")

    def test_apply_output(self) -> None:
        url = f"file://{self._lens_remote}"
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"{url}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_apply(proj, "v1.1.0")
        self.assertEqual(result.lens_repo_url, url)
        self.assertEqual(result.tag, "v1.1.0")


class TestResolveReleaseProjectRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_single_project_cwd_returns_project_root(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = resolve_release_project_root(proj)
        self.assertEqual(result, proj.resolve())

    def test_multi_project_resolves_to_leader(self) -> None:
        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        leader_block = (
            "[release]\n"
            "enabled = true\n"
            "app_leader = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
        )
        _init_project_repo_at(deploy_dir / "a", leader_block)
        _init_project_repo_at(deploy_dir / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(deploy_dir, ["a", "b"])

        result = resolve_release_project_root(deploy_dir)
        self.assertEqual(result, deploy_dir / "a")

    def test_multi_project_no_leader_raises(self) -> None:
        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        _init_project_repo_at(deploy_dir / "a", "[project]\ndatasets = ['testing']\n")
        _init_project_repo_at(deploy_dir / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(deploy_dir, ["a", "b"])

        with self.assertRaises(LensException) as ctx:
            resolve_release_project_root(deploy_dir)
        self.assertIn("app_leader", str(ctx.exception))

    def test_multi_project_two_leaders_raises(self) -> None:
        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        block = "[release]\nenabled = true\napp_leader = true\n"
        _init_project_repo_at(deploy_dir / "a", block)
        _init_project_repo_at(deploy_dir / "b", block)
        _write_fly_toml(deploy_dir, ["a", "b"])

        with self.assertRaises(LensException):
            resolve_release_project_root(deploy_dir)

    def test_colocated_leader_fly_toml_resolves_from_grandparent(self) -> None:
        """fly.toml lives inside the leader's own project dir; running from
        the grandparent (bare directory with no lens.toml/fly.toml of its
        own) still resolves to the leader — see "Multi-project deployments"
        in deploy/README.md."""
        grandparent = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        grandparent.mkdir()
        leader_block = (
            "[release]\n"
            "enabled = true\n"
            "app_leader = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
        )
        leader_root = _init_project_repo_at(grandparent / "a", leader_block)
        _init_project_repo_at(grandparent / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(leader_root, ["a", "b"])

        result = resolve_release_project_root(grandparent)
        self.assertEqual(result, leader_root)
