"""Tests for the release decision engine commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from lens.core.commands.release import (
    execute_release_apply,
    execute_release_check,
    execute_release_gated_reject,
    resolve_release_project_root,
)
from lens.core.project import ProjectSession
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
        self._find_lens_patch = mock.patch(
            "lens.core.release.status.find_lens_repo_root", return_value=None
        )
        self._find_lens_patch.start()

    def tearDown(self) -> None:
        self._find_lens_patch.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_check_disabled_returns_none(self) -> None:
        proj = _init_project_repo(self._tmp_path, "[project]\ndatasets = ['testing']\n")
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_check_pending_gated_awaits(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = false\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "await_approval")
        self.assertEqual(result.target, "v2.0.0")

    def test_check_pending_gated_still_allows_minor(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"minor\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = false\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.0.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v1.1.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("gated_update_pending = true", contents)

    def test_check_auto_minor_applies(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"minor\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.0.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v1.1.0")

    def test_check_auto_major_marks_gated_pending(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"major\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.1.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "await_approval")
        self.assertEqual(result.target, "v2.0.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("gated_update_pending = true", contents)

    def test_check_requested_version_downgrade_rejected(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.0.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.1.0"}, clear=False):
            with self.assertRaises(LensException):
                execute_release_check(proj)

    def test_check_pending_and_approved_returns_apply(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = true\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v2.0.0")

    def test_check_pending_approved_missing_target_raises(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"\"\n"
            "gated_update_approved = true\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with self.assertRaises(LensException):
            execute_release_check(proj)

    def test_check_already_at_target_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"minor\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.1.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_check_requested_version_equals_installed_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.1.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.1.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_check_requested_version_applies_when_newer(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v2.0.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.1.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "await_approval")
        self.assertEqual(result.target, "v2.0.0")

    def test_check_requested_version_unparseable_raises(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"not-a-valid-version\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with self.assertRaises(LensException):
            execute_release_check(proj)

    def test_check_auto_off_no_requested_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"off\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_check_auto_minor_no_installed_returns_none(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"minor\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

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

    def test_apply_no_approval_does_not_commit(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_apply(proj, "v1.1.0")
        self.assertEqual(result.tag, "v1.1.0")
        # No commit was made (not an approved gated bump), so lens.toml is unchanged
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertNotIn("gated_update_pending", contents)

    def test_apply_clears_gated_fields_when_approved(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = true\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        result = execute_release_apply(proj, "v2.0.0")
        self.assertEqual(result.tag, "v2.0.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("gated_update_pending = false", contents)
        self.assertIn("gated_update_approved = false", contents)
        self.assertIn("gated_update_target_version = \"\"", contents)

    def test_check_auto_major_no_tags_returns_none(self) -> None:
        no_tags_remote = _init_bare_repo_with_tags(self._tmp_path, [])
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{no_tags_remote}\"\n"
            "auto_update = \"major\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.0.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "none")

    def test_update_release_section_preserves_other_sections(self) -> None:
        """_update_release_section should not touch unrelated config sections."""
        block = (
            "[project]\n"
            'datasets = ["testing"]\n'
            "\n"
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "auto_update = \"minor\"\n"
            "\n"
            "[[llm]]\n"
            'base_url = "http://localhost:11434/v1"\n'
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.0.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "apply")
        self.assertEqual(result.target, "v1.1.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("base_url = \"http://localhost:11434/v1\"", contents)
        self.assertIn('datasets = ["testing"]', contents)

    def test_reject_clears_gated_fields(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = false\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        session = ProjectSession(proj, proj)
        execute_release_gated_reject(session)
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("gated_update_pending = false", contents)
        self.assertIn("gated_update_approved = false", contents)
        self.assertIn("gated_update_target_version = \"\"", contents)

    def test_reject_noop_when_no_pending(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        before = (proj / "lens.toml").read_text(encoding="utf-8")
        session = ProjectSession(proj, proj)
        execute_release_gated_reject(session)
        after = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_apply_clears_requested_version_when_fulfilled(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.1.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        execute_release_apply(proj, "v1.1.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("requested_version = \"\"", contents)

    def test_apply_does_not_clear_requested_version_for_different_tag(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v2.0.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        execute_release_apply(proj, "v1.0.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("requested_version = \"v2.0.0\"", contents)

    def test_apply_combines_gated_clear_and_requested_clear(self) -> None:
        """Clearing both gated-update and requested_version in a single commit."""
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "gated_update_pending = true\n"
            "gated_update_target_version = \"v2.0.0\"\n"
            "gated_update_approved = true\n"
            "requested_version = \"v2.0.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        execute_release_apply(proj, "v2.0.0")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("gated_update_pending = false", contents)
        self.assertIn("gated_update_approved = false", contents)
        self.assertIn("gated_update_target_version = \"\"", contents)
        self.assertIn("requested_version = \"\"", contents)

    def test_check_clears_requested_version_when_already_installed(self) -> None:
        block = (
            "[release]\n"
            "enabled = true\n"
            f"lens_repo_url = \"file://{self._lens_remote}\"\n"
            "requested_version = \"v1.0.0\"\n"
        )
        proj = _init_project_repo(self._tmp_path, block)
        with mock.patch.dict(os.environ, {"LENS_VERSION": "v1.0.0"}, clear=False):
            result = execute_release_check(proj)
        self.assertEqual(result.action, "none")
        contents = (proj / "lens.toml").read_text(encoding="utf-8")
        self.assertIn("requested_version = \"\"", contents)


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

    def test_no_lens_toml_no_fly_toml_raises_runtime_error(self) -> None:
        empty_dir = self._tmp_path / f"empty_{uuid.uuid4().hex}"
        empty_dir.mkdir()
        with self.assertRaises(RuntimeError):
            resolve_release_project_root(empty_dir)

    def test_running_from_inside_sibling_project_uses_that_project(self) -> None:
        """Running from inside a specific sibling still targets that project,
        not the leader — matches ordinary `lens` command behavior."""
        deploy_dir = self._tmp_path / f"deploy_{uuid.uuid4().hex}"
        deploy_dir.mkdir()
        leader_block = "[release]\nenabled = true\napp_leader = true\n"
        _init_project_repo_at(deploy_dir / "a", leader_block)
        _init_project_repo_at(deploy_dir / "b", "[project]\ndatasets = ['testing']\n")
        _write_fly_toml(deploy_dir, ["a", "b"])

        result = resolve_release_project_root(deploy_dir / "b")
        self.assertEqual(result, (deploy_dir / "b").resolve())
