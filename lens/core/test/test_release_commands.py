"""Tests for the release decision engine commands.

All tests that involve parent-hash matching create real git commits in
temporary repositories so that ``git rev-list`` and related commands work.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path

from lens.core.commands.release import (
    execute_release_apply,
    execute_release_check,
    execute_release_clear,
    execute_release_request,
    execute_release_secrets_check,
    execute_release_secrets_sync,
    resolve_release_project_root,
)
from lens.core.exceptions import LensException


def _init_bare_repo_with_tags(base: Path, tags: list[str]) -> Path:
    bare = base / f"lens_remote_{uuid.uuid4().hex}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)

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
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
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
        self.assertEqual(result.target, "1.1.0")

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

    def test_check_with_since_range_multi_commit_exactly_once(self) -> None:
        """A push carrying two commits: only the first has
        requested_from_commit as its parent — deploy fires exactly once."""
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

        # Push 1: since=before, range=before..HEAD
        # Parents of commits in range: [C1_sha, before] — before matches
        result = execute_release_check(proj, since=before)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "1.1.0")

        # Simulate second push: another commit on top (carrying stale request forward)
        after_c2 = _make_commit(proj, "unrelated work after deploy")

        # Push 2: since=after_c2's parent (= HEAD~1), range=<parent>..HEAD
        # Parents of commits in range: the parent is after_c2's parent (C2's parent = C1),
        # not "before" — no match
        first_parent = subprocess.run(
            ["git", "rev-parse", f"{after_c2}^1"],
            cwd=proj, capture_output=True, text=True,
        ).stdout.strip()
        result2 = execute_release_check(proj, since=first_parent)
        self.assertEqual(result2.action, "none")

    def test_check_stale_request_carried_forward_spent(self) -> None:
        """requested_from_commit lives in a commit before the push range
        and is carried forward unchanged — should not match."""
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        c0 = _get_head_sha(proj)

        # Commit the request at C0
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.1.0\"\n"
            f"requested_from_commit = \"{c0}\"\n"
        )
        (proj / "lens.toml").write_text(block)
        subprocess.run(["git", "add", "lens.toml"], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "set request at c0"],
            cwd=proj, check=True, capture_output=True,
        )
        c1 = _get_head_sha(proj)  # child of c0

        # Two more commits carry the (now stale) request forward unchanged
        _make_commit(proj, "work after request")
        _make_commit(proj, "more work after request")

        # Push 1: c0..c1 (the commit that first carries the request)
        result = execute_release_check(proj, since=c0)
        self.assertEqual(result.action, "apply")

        # Push 2: c1..HEAD — neither commit has c0 as parent → no match
        result2 = execute_release_check(proj, since=c1)
        self.assertEqual(result2.action, "none")

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
        self.assertEqual(result.tag, "1.1.0")
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
        self.assertEqual(result.tag, "1.1.0")


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


class TestExecuteReleaseRequest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_request_writes_both_fields(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = execute_release_request(proj, "v1.1.0")
        self.assertEqual(result.requested_version, "1.1.0")
        self.assertTrue(len(result.requested_from_commit) > 0)

        parsed = tomllib.loads((proj / "lens.toml").read_text())
        release = parsed.get("release", {})
        self.assertEqual(release.get("requested_version"), "1.1.0")
        self.assertEqual(release.get("requested_from_commit"), result.requested_from_commit)

    def test_request_never_commits(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        before = _get_head_sha(proj)
        execute_release_request(proj, "v2.0.0")
        after = _get_head_sha(proj)
        self.assertEqual(before, after, "request should not create a commit")

    def test_request_invalid_tag_raises(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        with self.assertRaises(LensException):
            execute_release_request(proj, "not-a-valid-tag")

    def test_request_creates_release_section_when_missing(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        execute_release_request(proj, "v1.0.0")
        parsed = tomllib.loads((proj / "lens.toml").read_text())
        self.assertIn("release", parsed)
        self.assertEqual(parsed["release"]["requested_version"], "1.0.0")

    def test_request_preserves_existing_release_fields(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
            'requested_version = "v1.0.0"\n'
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_request(proj, "v2.0.0")
        parsed = tomllib.loads((proj / "lens.toml").read_text())
        release = parsed["release"]
        self.assertEqual(release["requested_version"], "2.0.0")
        self.assertEqual(release["requested_from_commit"], result.requested_from_commit)
        # Existing fields are preserved
        self.assertTrue(release["enabled"])
        self.assertEqual(release["lens_repo_url"], "https://example.com/lens.git")


class TestExecuteReleaseClear(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _request(self, proj: Path, tag: str = "v1.1.0") -> str:
        result = execute_release_request(proj, tag)
        return result.requested_from_commit

    def test_clears_both_fields(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        self._request(proj, "v2.0.0")

        execute_release_clear(proj)

        parsed = tomllib.loads((proj / "lens.toml").read_text())
        release = parsed.get("release", {})
        self.assertEqual(release.get("requested_version"), "")
        self.assertEqual(release.get("requested_from_commit"), "")

    def test_never_commits(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        self._request(proj)
        before = _get_head_sha(proj)
        execute_release_clear(proj)
        after = _get_head_sha(proj)
        self.assertEqual(before, after, "clear should not create a commit")

    def test_clear_when_already_empty_is_noop(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
            "requested_version = \"\"\n"
            "requested_from_commit = \"\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        before = _get_head_sha(proj)
        result = execute_release_clear(proj)
        after = _get_head_sha(proj)
        self.assertEqual(before, after)
        self.assertIn("nothing to clear", result.summary)

    def test_clear_when_no_release_section_is_noop(self) -> None:
        proj = _init_project_repo(self._tmp_path, "")
        before = _get_head_sha(proj)
        result = execute_release_clear(proj)
        after = _get_head_sha(proj)
        self.assertEqual(before, after)
        self.assertIn("no [release] section", result.summary)

    def test_clear_preserves_other_release_fields(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
            'requested_version = "v1.0.0"\n'
        )
        proj = _init_project_repo(self._tmp_path, block)
        execute_release_clear(proj)
        parsed = tomllib.loads((proj / "lens.toml").read_text())
        release = parsed["release"]
        self.assertEqual(release["requested_version"], "")
        self.assertEqual(release["requested_from_commit"], "")
        self.assertTrue(release["enabled"])
        self.assertEqual(release["lens_repo_url"], "https://example.com/lens.git")


class TestSecretsSync(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)
        self._env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_lenstoml(self, project: Path, extra: str = "") -> None:
        (project / "lens.toml").write_text(
            "[release]\nenabled = true\nlens_repo_url = \"https://example.com/lens.git\"\n"
            + extra
        )

    def _init_leader(self) -> Path:
        """Create a leader project with a git remote and lens.toml."""
        project = self._tmp_path / f"leader_{uuid.uuid4().hex}"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
        self._make_lenstoml(project)
        subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)
        remote = self._tmp_path / f"leader_remote_{uuid.uuid4().hex}.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=project, check=True, capture_output=True)
        return project

    def _init_dependent_bare(self, name: str) -> Path:
        """Create a bare repo that a dependent clone target can reference."""
        remote = self._tmp_path / f"{name}_remote_{uuid.uuid4().hex}.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
        clone = self._tmp_path / f"{name}_clone_{uuid.uuid4().hex}"
        subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True)
        (clone / "lens.toml").write_text(
            "[project]\ndatasets = ['testing']\n"
            "[[llm]]\nprovider = 'openai'\napi_key_env = 'DEPENDENT_OPENAI_KEY'\n"
        )
        subprocess.run(["git", "add", "lens.toml"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=clone, check=True, capture_output=True)
        shutil.rmtree(clone, ignore_errors=True)
        return remote

    def test_disabled_release_raises(self) -> None:
        project = self._tmp_path / "disabled"
        project.mkdir()
        (project / "lens.toml").write_text("[project]\ndatasets = ['testing']\n")
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
        subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True
        )
        with self.assertRaises(LensException):
            execute_release_secrets_sync(project, "my-app", dry_run=True)

    def test_leader_only_sets_slugs(self) -> None:
        leader = self._init_leader()
        result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
        self.assertEqual(result.status, "ok")
        self.assertIn("LENS_PROJECT_SLUGS", result.collected_secrets)
        self.assertEqual(result.collected_secrets["LENS_PROJECT_SLUGS"], leader.name)
        # PROJECT_REPO_URL_* is set once by lens deploy init, not synced by CI
        env_key = leader.name.upper().replace("-", "_")
        self.assertNotIn(f"PROJECT_REPO_URL_{env_key}", result.collected_secrets)

    def test_additive_api_keys_collected_when_set(self) -> None:
        leader = self._init_leader()
        leader_raw = tomllib.loads((leader / "lens.toml").read_text())
        leader_raw.setdefault("llm", []).append({
            "provider": "openai",
            "api_key_env": "LEADER_OPENAI_KEY",
        })
        with (leader / "lens.toml").open("wb") as f:
            import tomli_w
            tomli_w.dump(leader_raw, f)
        subprocess.run(["git", "add", "lens.toml"], cwd=leader, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add llm config"],
            cwd=leader, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=leader, check=True, capture_output=True)

        os.environ["LEADER_OPENAI_KEY"] = "sk-test123"
        try:
            result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
            self.assertIn("LEADER_OPENAI_KEY", result.collected_secrets)
            self.assertEqual(result.collected_secrets["LEADER_OPENAI_KEY"], "sk-test123")
        finally:
            os.environ.pop("LEADER_OPENAI_KEY", None)

    def test_additive_api_keys_skipped_when_not_set(self) -> None:
        leader = self._init_leader()
        leader_raw = tomllib.loads((leader / "lens.toml").read_text())
        leader_raw.setdefault("llm", []).append({
            "provider": "openai",
            "api_key_env": "LEADER_OPENAI_KEY",
        })
        with (leader / "lens.toml").open("wb") as f:
            import tomli_w
            tomli_w.dump(leader_raw, f)
        subprocess.run(["git", "add", "lens.toml"], cwd=leader, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add llm config"],
            cwd=leader, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=leader, check=True, capture_output=True)

        # Do NOT set LEADER_OPENAI_KEY in env — should be silently skipped
        result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
        self.assertNotIn("LEADER_OPENAI_KEY", result.collected_secrets)

    def test_deploy_key_collected_when_set(self) -> None:
        leader = self._init_leader()
        env_key = leader.name.upper().replace("-", "_")
        deploy_key_var = f"GIT_REPO_DEPLOY_KEY_{env_key}"
        os.environ[deploy_key_var] = "fake-key-content"
        try:
            result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
            self.assertIn(deploy_key_var, result.collected_secrets)
            self.assertEqual(result.collected_secrets[deploy_key_var], "fake-key-content")
        finally:
            os.environ.pop(deploy_key_var, None)

    def test_dataset_deploy_key_collected_when_set(self) -> None:
        leader = self._init_leader()
        leader_raw = tomllib.loads((leader / "lens.toml").read_text())
        leader_raw.setdefault("dataset_repo", []).append({
            "name": "my-ds",
            "git_url": "https://example.com/my-ds.git",
        })
        with (leader / "lens.toml").open("wb") as f:
            import tomli_w
            tomli_w.dump(leader_raw, f)
        subprocess.run(["git", "add", "lens.toml"], cwd=leader, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add dataset repo"],
            cwd=leader, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=leader, check=True, capture_output=True)

        os.environ["DATASET_REPO_DEPLOY_KEY_MY_DS"] = "ds-key-content"
        try:
            result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
            self.assertIn("DATASET_REPO_DEPLOY_KEY_MY_DS", result.collected_secrets)
            self.assertEqual(
                result.collected_secrets["DATASET_REPO_DEPLOY_KEY_MY_DS"], "ds-key-content"
            )
        finally:
            os.environ.pop("DATASET_REPO_DEPLOY_KEY_MY_DS", None)

    def test_with_dependent_sets_slugs_and_clones(self) -> None:
        leader = self._init_leader()
        dep_name = "my-other-app"
        dep_remote = self._init_dependent_bare(dep_name)

        # Add [[dependent_project]] to leader config
        leader_raw = tomllib.loads((leader / "lens.toml").read_text())
        leader_raw.setdefault("dependent_project", []).append({
            "name": dep_name,
            "git_url": str(dep_remote),
            "ref": "main",
        })
        with (leader / "lens.toml").open("wb") as f:
            import tomli_w
            tomli_w.dump(leader_raw, f)
        subprocess.run(["git", "add", "lens.toml"], cwd=leader, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add dependent_project"],
            cwd=leader, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=leader, check=True, capture_output=True)

        # Set dependent's API key in env
        os.environ["DEPENDENT_OPENAI_KEY"] = "sk-dependent"
        try:
            result = execute_release_secrets_sync(leader, "my-app", dry_run=True)
            # Expected slugs: leader + dependent
            slugs = result.collected_secrets.get("LENS_PROJECT_SLUGS", "")
            self.assertIn(leader.name, slugs)
            self.assertIn(dep_name, slugs)

            # Dependent's API key from its lens.toml should be collected
            self.assertIn("DEPENDENT_OPENAI_KEY", result.collected_secrets)
            self.assertEqual(result.collected_secrets["DEPENDENT_OPENAI_KEY"], "sk-dependent")

            # PROJECT_REPO_URL_* is set once by lens deploy init, not synced by CI
            dep_env_key = dep_name.upper().replace("-", "_")
            self.assertNotIn(f"PROJECT_REPO_URL_{dep_env_key}", result.collected_secrets)
        finally:
            os.environ.pop("DEPENDENT_OPENAI_KEY", None)


class TestSecretsCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)
        self._env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _init_leader(self, extra_toml: str = "") -> Path:
        project = self._tmp_path / f"leader_{uuid.uuid4().hex}"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
        (project / "lens.toml").write_text(
            "[release]\nenabled = true\nlens_repo_url = \"https://example.com/lens.git\"\n"
            + extra_toml
        )
        subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True
        )
        remote = self._tmp_path / f"leader_remote_{uuid.uuid4().hex}.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project, check=True)
        subprocess.run(
            ["git", "push", "-u", "origin", "main"], cwd=project, check=True, capture_output=True
        )
        return project

    def _init_dependent_bare(self, name: str, extra_toml: str = "") -> Path:
        remote = self._tmp_path / f"{name}_remote_{uuid.uuid4().hex}.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
        clone = self._tmp_path / f"{name}_clone_{uuid.uuid4().hex}"
        subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True)
        (clone / "lens.toml").write_text(
            "[project]\ndatasets = ['testing']\n"
            "[[llm]]\nprovider = 'openai'\napi_key_env = 'DEPENDENT_OPENAI_KEY'\n"
            + extra_toml
        )
        subprocess.run(["git", "add", "lens.toml"], cwd=clone, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=clone, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"], cwd=clone, check=True, capture_output=True
        )
        shutil.rmtree(clone, ignore_errors=True)
        return remote

    def test_disabled_release_raises(self) -> None:
        project = self._tmp_path / "disabled"
        project.mkdir()
        (project / "lens.toml").write_text("[project]\ndatasets = ['testing']\n")
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
        subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True
        )
        with self.assertRaises(LensException):
            execute_release_secrets_check(project)

    def test_leader_only_reports_api_key_and_deploy_key(self) -> None:
        extra = (
            "[[llm]]\nprovider = 'openai'\napi_key_env = 'TEST_OPENAI_KEY'\n"
            "[[image]]\nprovider = 'dalle'\napi_key_env = 'TEST_DALLE_KEY'\n"
        )
        leader = self._init_leader(extra)

        result = execute_release_secrets_check(leader)
        self.assertEqual(result.leader_slug, leader.name)
        self.assertEqual(result.project_slugs, [leader.name])

        names = {s.name for s in result.secrets}
        self.assertIn("TEST_OPENAI_KEY", names)
        self.assertIn("TEST_DALLE_KEY", names)
        leader_key_var = f"GIT_REPO_DEPLOY_KEY_{leader.name.upper().replace('-', '_')}"
        self.assertIn(leader_key_var, names)
        self.assertIn("FLY_API_TOKEN", names)

    def test_api_key_env_status_reflects_local_env(self) -> None:
        extra = "[[llm]]\nprovider = 'openai'\napi_key_env = 'TEST_OPENAI_KEY'\n"
        leader = self._init_leader(extra)
        os.environ["TEST_OPENAI_KEY"] = "sk-set"

        result = execute_release_secrets_check(leader)
        api_key_req = [s for s in result.secrets if s.name == "TEST_OPENAI_KEY"]
        self.assertEqual(len(api_key_req), 1)
        self.assertTrue(api_key_req[0].set_in_env)

    def test_api_key_env_shows_unset_when_not_in_env(self) -> None:
        extra = "[[llm]]\nprovider = 'openai'\napi_key_env = 'TEST_UNSET_KEY'\n"
        leader = self._init_leader(extra)

        result = execute_release_secrets_check(leader)
        api_key_req = [s for s in result.secrets if s.name == "TEST_UNSET_KEY"]
        self.assertEqual(len(api_key_req), 1)
        self.assertFalse(api_key_req[0].set_in_env)

    def test_dataset_repo_deploy_key_appears(self) -> None:
        extra = (
            "[[dataset_repo]]\nname = 'lens-dnd'\ngit_url = 'https://github.com/org/lens-dnd.git'\n"
        )
        leader = self._init_leader(extra)

        result = execute_release_secrets_check(leader)
        ds_key_var = "DATASET_REPO_DEPLOY_KEY_LENS_DND"
        ds_keys = [s for s in result.secrets if s.name == ds_key_var]
        self.assertEqual(len(ds_keys), 1)
        self.assertEqual(ds_keys[0].source, "dataset_repo: lens-dnd")

    def test_dependent_project_keys_and_api_keys(self) -> None:
        leader = self._init_leader()
        dep_name = "my-other-app"
        dep_remote = self._init_dependent_bare(dep_name)

        leader_raw = tomllib.loads((leader / "lens.toml").read_text())
        leader_raw.setdefault("dependent_project", []).append({
            "name": dep_name,
            "git_url": str(dep_remote),
            "ref": "main",
        })
        with (leader / "lens.toml").open("wb") as f:
            import tomli_w
            tomli_w.dump(leader_raw, f)
        subprocess.run(
            ["git", "add", "lens.toml"], cwd=leader, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "add dependent_project"],
            cwd=leader, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=leader, check=True, capture_output=True)

        result = execute_release_secrets_check(leader)

        # Dependent's API key from its lens.toml should appear
        dep_api = [s for s in result.secrets if s.name == "DEPENDENT_OPENAI_KEY"]
        self.assertEqual(len(dep_api), 1)
        self.assertIn("my-other-app", dep_api[0].source)

        # Dependent's deploy key should appear
        dep_key_var = f"GIT_REPO_DEPLOY_KEY_{dep_name.upper().replace('-', '_')}"
        dep_key = [s for s in result.secrets if s.name == dep_key_var]
        self.assertEqual(len(dep_key), 1)

        # Project slugs should include both
        self.assertIn(leader.name, result.project_slugs)
        self.assertIn(dep_name, result.project_slugs)

    def test_fly_app_read_from_fly_toml(self) -> None:
        extra = "[[llm]]\nprovider = 'openai'\napi_key_env = 'TEST_KEY'\n"
        leader = self._init_leader(extra)
        (leader / "fly.toml").write_text('app = "my-fly-app"\n')

        result = execute_release_secrets_check(leader)
        self.assertEqual(result.fly_app, "my-fly-app")
