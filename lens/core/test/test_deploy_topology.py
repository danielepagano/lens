"""Tests for multi-project deploy directory/topology resolution.

Covers the "leader-colocated" topology (see "Multi-project deployments" in
``deploy/README.md``), where ``fly.toml`` lives inside the release leader's
own project directory instead of a separate bare parent-of-projects
directory, and the tiered slug -> project-root resolution
(:func:`resolve_project_root_for_slug` / :func:`build_projects`) that makes
both topologies work interchangeably.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.commands.deploy import (
    _validate_release_topology,  # pyright: ignore[reportPrivateUsage]
    build_projects,
    find_colocated_fly_toml,
    init_deploy,
    resolve_deploy_dir,
)
from lens.core.exceptions import LensException


def _write_project(root: Path, slug: str, lens_toml: str = "") -> Path:
    project = root / slug
    project.mkdir(parents=True)
    (project / ".git").mkdir()  # find_git_root_from only checks for a .git dir
    (project / "lens.toml").write_text(lens_toml, encoding="utf-8")
    return project


def _write_fly_toml(directory: Path, slugs: list[str]) -> Path:
    fly_toml = directory / "fly.toml"
    fly_toml.write_text(
        'app = "my-app"\n'
        "[env]\n"
        f'  LENS_PROJECT_SLUGS = "{",".join(slugs)}"\n'
    )
    return fly_toml


class BuildProjectsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_bare_parent_topology_child_resolution(self) -> None:
        deploy_dir = self._tmp_path / "deploy"
        deploy_dir.mkdir()
        _write_project(deploy_dir, "a")
        _write_project(deploy_dir, "b")

        projects = build_projects(deploy_dir, ["a", "b"])
        self.assertEqual(
            [(slug, root) for slug, _git, root in projects],
            [("a", deploy_dir / "a"), ("b", deploy_dir / "b")],
        )

    def test_single_project_self_resolution(self) -> None:
        project = _write_project(self._tmp_path, "solo").resolve()

        projects = build_projects(project, ["solo"])
        self.assertEqual(projects, [("solo", project, project)])

    def test_leader_colocated_topology_cousin_resolution(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader", "[release]\napp_leader = true\n")
        sibling = _write_project(parent, "sibling")

        # deploy_dir is the leader's own directory; "sibling" must resolve
        # as a cousin (deploy_dir.parent / slug), not a child.
        projects = build_projects(leader, ["leader", "sibling"])
        self.assertEqual(
            [(slug, root) for slug, _git, root in projects],
            [("leader", leader), ("sibling", sibling)],
        )

    def test_unresolvable_slug_raises(self) -> None:
        deploy_dir = self._tmp_path / "deploy"
        deploy_dir.mkdir()
        with self.assertRaises(LensException) as ctx:
            build_projects(deploy_dir, ["missing"])
        self.assertIn("missing", str(ctx.exception))


class FindColocatedFlyTomlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_finds_child_with_both_files(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader")
        _write_fly_toml(leader, ["leader", "sibling"])

        found = find_colocated_fly_toml(parent)
        self.assertEqual(found, leader / "fly.toml")

    def test_returns_none_when_no_child_qualifies(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        _write_project(parent, "a")  # lens.toml but no fly.toml
        self.assertIsNone(find_colocated_fly_toml(parent))

    def test_returns_none_for_non_directory(self) -> None:
        missing = self._tmp_path / "does-not-exist"
        self.assertIsNone(find_colocated_fly_toml(missing))


class ResolveDeployDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_direct_fly_toml_at_cwd(self) -> None:
        deploy_dir = self._tmp_path / "deploy"
        deploy_dir.mkdir()
        _write_fly_toml(deploy_dir, ["a"])
        self.assertEqual(resolve_deploy_dir(deploy_dir), deploy_dir.resolve())

    def test_ancestor_project_with_fly_toml(self) -> None:
        project = _write_project(self._tmp_path, "solo")
        _write_fly_toml(project, ["solo"])
        subdir = project / "narrative"
        subdir.mkdir()
        self.assertEqual(resolve_deploy_dir(subdir), project.resolve())

    def test_colocated_leader_from_grandparent(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader")
        _write_fly_toml(leader, ["leader", "sibling"])
        _write_project(parent, "sibling")

        self.assertEqual(resolve_deploy_dir(parent), leader.resolve())

    def test_raises_when_nothing_found(self) -> None:
        empty = self._tmp_path / "empty"
        empty.mkdir()
        with self.assertRaises(LensException):
            resolve_deploy_dir(empty)


class DependentProjectDeployedTests(unittest.TestCase):
    """A ``[[dependent_project]]`` entry must correspond to a deployed slug.

    The entry alone only tells CI about the topology — the container derives
    the projects it serves from the ``PROJECT_REPO_URL_*`` Fly secrets that
    ``lens release add`` writes.  A hand-added entry would otherwise deploy
    nothing and fail silently.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @staticmethod
    def _leader_toml(*dependent_names: str) -> str:
        text = (
            "[release]\nenabled = true\napp_leader = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n'
        )
        for name in dependent_names:
            text += (
                "\n[[dependent_project]]\n"
                f'name = "{name}"\n'
                f'git_url = "git@example.com:org/{name}.git"\n'
            )
        return text

    def test_raises_when_dependent_is_not_a_deployed_slug(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader", self._leader_toml("ghost"))
        _write_project(parent, "sibling")

        projects = build_projects(leader, ["leader", "sibling"])
        with self.assertRaises(LensException) as ctx:
            _validate_release_topology(projects)
        message = str(ctx.exception)
        self.assertIn("ghost", message)
        self.assertIn("lens release add", message)

    def test_raises_for_single_project_leader(self) -> None:
        # The cross-project checks are skipped for one project, but a lone
        # leader can still declare a dependent that was never added.
        leader = _write_project(self._tmp_path, "leader", self._leader_toml("ghost"))

        projects = build_projects(leader, ["leader"])
        with self.assertRaises(LensException) as ctx:
            _validate_release_topology(projects)
        self.assertIn("ghost", str(ctx.exception))

    def test_passes_when_dependent_is_deployed(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader", self._leader_toml("sibling"))
        _write_project(parent, "sibling")

        projects = build_projects(leader, ["leader", "sibling"])
        self.assertEqual(_validate_release_topology(projects), leader)

    def test_ignores_entries_on_non_release_projects(self) -> None:
        # Only the release leader's topology governs the deployment; a stray
        # entry in a non-release sibling's lens.toml is not our business.
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(parent, "leader", self._leader_toml())
        _write_project(
            parent,
            "sibling",
            "[[dependent_project]]\n"
            'name = "ghost"\ngit_url = "git@example.com:org/ghost.git"\n',
        )

        projects = build_projects(leader, ["leader", "sibling"])
        self.assertEqual(_validate_release_topology(projects), leader)


class InitDeployLeaderTargetingTests(unittest.TestCase):
    """``init_deploy`` writes fly.toml into the designated leader's own
    directory in multi-project mode, instead of the bare parent dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)
        self._deploy_key = self._tmp_path / "deploy_key"
        self._deploy_key.write_text("fake-key")

        self._run_patch = mock.patch("lens.core.commands.deploy._run")
        self._run_patch.start()

        def _fake_validate(slug: str, project_root: Path, git_root: Path) -> str:
            return f"git@example.com:org/{slug}.git"

        self._validate_patch = mock.patch(
            "lens.core.commands.deploy._validate_project_for_deploy",
            side_effect=_fake_validate,
        )
        self._validate_patch.start()

    def tearDown(self) -> None:
        self._run_patch.stop()
        self._validate_patch.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_writes_fly_toml_inside_leader_when_designated(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        leader = _write_project(
            parent,
            "leader",
            "[release]\nenabled = true\napp_leader = true\n"
            'lens_repo_url = "https://example.com/lens.git"\n',
        )
        sibling = _write_project(parent, "sibling")

        fly_toml = init_deploy(
            deploy_dir=parent,
            app_name="my-app",
            region="lax",
            username="user",
            password="pw",
            deploy_keys={"leader": self._deploy_key, "sibling": self._deploy_key},
        )

        self.assertEqual(fly_toml, leader / "fly.toml")
        self.assertTrue(fly_toml.exists())
        self.assertFalse((parent / "fly.toml").exists())
        self.assertFalse((sibling / "fly.toml").exists())

    def test_writes_fly_toml_to_deploy_dir_when_no_leader(self) -> None:
        parent = self._tmp_path / "parent"
        parent.mkdir()
        _write_project(parent, "a")
        _write_project(parent, "b")

        fly_toml = init_deploy(
            deploy_dir=parent,
            app_name="my-app",
            region="lax",
            username="user",
            password="pw",
            deploy_keys={"a": self._deploy_key, "b": self._deploy_key},
        )

        self.assertEqual(fly_toml, parent / "fly.toml")


if __name__ == "__main__":
    unittest.main()
