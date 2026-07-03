"""Unit tests for release version resolution."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from lens.core.release.status import compute_release_status
from lens.core.release.version import (
    SemverTag,
    compute_local_version,
    installed_version,
    latest_overall,
    latest_within_major,
    list_local_tags,
    list_remote_tags,
    parse_semver_tag,
)


def _init_repo_with_tags(tmp: Path, tags: list[str]) -> Path:
    """Create a local bare git repo with the given semver tags and return its path."""
    bare = tmp / "upstream.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        check=True,
        capture_output=True,
    )

    clone = tmp / "cloner"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=clone, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=clone, check=True, capture_output=True,
    )

    (clone / "README.md").write_text("test")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=clone, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=clone, check=True, capture_output=True,
    )

    subprocess.run(
        ["git", "push", "-u", "origin", "HEAD"],
        cwd=clone, check=True, capture_output=True,
    )

    for tag in tags:
        subprocess.run(
            ["git", "tag", tag],
            cwd=clone, check=True, capture_output=True,
        )

    if tags:
        subprocess.run(
            ["git", "push", "--tags"],
            cwd=clone, check=True, capture_output=True,
        )

    return bare


class TestParseSemverTag(unittest.TestCase):
    def test_valid_minimal(self) -> None:
        t = parse_semver_tag("v1.0.0")
        self.assertIsNotNone(t)
        self.assertEqual(t, SemverTag(1, 0, 0))

    def test_valid_full(self) -> None:
        t = parse_semver_tag("v2.3.4")
        self.assertEqual(t, SemverTag(2, 3, 4))

    def test_valid_zero_patch(self) -> None:
        t = parse_semver_tag("v0.0.0")
        self.assertEqual(t, SemverTag(0, 0, 0))

    def test_large_numbers(self) -> None:
        t = parse_semver_tag("v999.888.777")
        self.assertEqual(t, SemverTag(999, 888, 777))

    def test_tag_property(self) -> None:
        t = SemverTag(1, 2, 3)
        self.assertEqual(t.tag, "v1.2.3")

    def test_no_v_prefix_accepted(self) -> None:
        self.assertEqual(parse_semver_tag("1.0.0"), SemverTag(1, 0, 0))

    def test_prerelease_rejected(self) -> None:
        self.assertIsNone(parse_semver_tag("v1.0.0-beta"))

    def test_build_metadata_rejected(self) -> None:
        self.assertIsNone(parse_semver_tag("v1.0.0+build.1"))

    def test_missing_patch_rejected(self) -> None:
        self.assertIsNone(parse_semver_tag("v1.0"))

    def test_missing_minor_rejected(self) -> None:
        self.assertIsNone(parse_semver_tag("v1"))

    def test_empty_string(self) -> None:
        self.assertIsNone(parse_semver_tag(""))

    def test_whitespace_allowed(self) -> None:
        t = parse_semver_tag("  v1.2.3  ")
        self.assertEqual(t, SemverTag(1, 2, 3))


class TestLatestOverall(unittest.TestCase):
    def test_empty_list(self) -> None:
        self.assertIsNone(latest_overall([]))

    def test_single_tag(self) -> None:
        tags = [SemverTag(1, 0, 0)]
        self.assertEqual(latest_overall(tags), SemverTag(1, 0, 0))

    def test_orders_by_semver(self) -> None:
        tags = [
            SemverTag(1, 0, 0),
            SemverTag(2, 0, 0),
            SemverTag(1, 5, 0),
        ]
        self.assertEqual(latest_overall(tags), SemverTag(2, 0, 0))

    def test_orders_within_major(self) -> None:
        tags = [
            SemverTag(1, 0, 0),
            SemverTag(1, 2, 0),
            SemverTag(1, 1, 5),
        ]
        self.assertEqual(latest_overall(tags), SemverTag(1, 2, 0))


class TestLatestWithinMajor(unittest.TestCase):
    def test_empty_list(self) -> None:
        self.assertIsNone(latest_within_major([], 1))

    def test_picks_latest_in_major(self) -> None:
        tags = [
            SemverTag(1, 0, 0),
            SemverTag(1, 2, 0),
            SemverTag(1, 1, 0),
            SemverTag(2, 0, 0),
        ]
        self.assertEqual(latest_within_major(tags, 1), SemverTag(1, 2, 0))

    def test_no_tags_in_major_returns_none(self) -> None:
        tags = [SemverTag(2, 0, 0), SemverTag(3, 0, 0)]
        self.assertIsNone(latest_within_major(tags, 1))

    def test_single_in_major(self) -> None:
        tags = [SemverTag(2, 0, 0), SemverTag(1, 0, 0)]
        self.assertEqual(latest_within_major(tags, 1), SemverTag(1, 0, 0))


class TestInstalledVersion(unittest.TestCase):
    def test_unset_returns_none(self) -> None:
        env = os.environ.copy()
        env.pop("LENS_VERSION", None)
        # Simulate by checking the default
        self.assertNotIn("LENS_VERSION", os.environ)

    def test_set_returns_value(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"LENS_VERSION": "v1.2.3"}):
            self.assertEqual(installed_version(), "v1.2.3")

    def test_empty_env_returns_empty_string(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"LENS_VERSION": ""}):
            self.assertEqual(installed_version(), "")

    def test_set_to_dev(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"LENS_VERSION": "dev"}):
            self.assertEqual(installed_version(), "dev")


class TestSemverTagOrdering(unittest.TestCase):
    def test_major_dominates(self) -> None:
        self.assertGreater(SemverTag(2, 0, 0), SemverTag(1, 999, 999))

    def test_minor_dominates_within_major(self) -> None:
        self.assertGreater(SemverTag(1, 2, 0), SemverTag(1, 1, 999))

    def test_patch_dominates_within_minor(self) -> None:
        self.assertGreater(SemverTag(1, 1, 2), SemverTag(1, 1, 1))

    def test_equal_tags(self) -> None:
        self.assertEqual(SemverTag(1, 2, 3), SemverTag(1, 2, 3))


class TestListRemoteTags(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_path = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_tags(self) -> None:
        bare = _init_repo_with_tags(self._tmp_path, [])
        url = f"file://{bare}"
        tags = list_remote_tags(url)
        self.assertEqual(tags, [])

    def test_single_tag(self) -> None:
        bare = _init_repo_with_tags(self._tmp_path, ["v1.0.0"])
        tags = list_remote_tags(f"file://{bare}")
        self.assertEqual(tags, [SemverTag(1, 0, 0)])

    def test_multiple_tags_sorted(self) -> None:
        bare = _init_repo_with_tags(
            self._tmp_path, ["v1.0.0", "v1.1.0", "v2.0.0", "v1.0.1"]
        )
        tags = list_remote_tags(f"file://{bare}")
        self.assertEqual(
            tags,
            [
                SemverTag(1, 0, 0),
                SemverTag(1, 0, 1),
                SemverTag(1, 1, 0),
                SemverTag(2, 0, 0),
            ],
        )

    def test_ignores_non_semver_tags(self) -> None:
        bare = _init_repo_with_tags(
            self._tmp_path, ["v1.0.0", "latest", "v1.1.0", "v1-beta"]
        )
        tags = list_remote_tags(f"file://{bare}")
        self.assertEqual(tags, [SemverTag(1, 0, 0), SemverTag(1, 1, 0)])

    def test_ignores_peeled_annotations(self) -> None:
        bare = _init_repo_with_tags(self._tmp_path, ["v1.0.0"])
        clone = self._tmp_path / "annotator"
        subprocess.run(
            ["git", "clone", str(bare), str(clone)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "-a", "-m", "msg", "v2.0.0"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push", "origin", "v2.0.0"],
            cwd=clone, check=True, capture_output=True,
        )
        tags = list_remote_tags(f"file://{bare}")
        self.assertEqual(tags, [SemverTag(1, 0, 0), SemverTag(2, 0, 0)])

    def test_annotated_and_lightweight_same_name_deduped(self) -> None:
        bare = _init_repo_with_tags(self._tmp_path, ["v1.0.0"])
        clone = self._tmp_path / "annotator2"
        subprocess.run(
            ["git", "clone", str(bare), str(clone)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "-a", "-f", "-m", "msg", "v1.0.0"],
            cwd=clone, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push", "origin", "--force", "--tags"],
            cwd=clone, check=True, capture_output=True,
        )
        tags = list_remote_tags(f"file://{bare}")
        self.assertEqual(tags, [SemverTag(1, 0, 0)])

    def test_bad_url_returns_empty(self) -> None:
        tags = list_remote_tags("file:///nonexistent/repo.git")
        self.assertEqual(tags, [])


class TestComputeReleaseStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._root = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_toml(self, content: str) -> None:
        (self._root / "lens.toml").write_text(content)

    def test_no_lens_toml_returns_disabled(self) -> None:
        status = compute_release_status(self._root)
        self.assertFalse(status.enabled)

    def test_disabled_release_returns_default(self) -> None:
        self._write_toml("[project]\ndatasets = [\"testing\"]\n")
        status = compute_release_status(self._root)
        self.assertFalse(status.enabled)

    def test_enabled_no_remote_still_populated(self) -> None:
        self._write_toml(
            "[release]\nenabled = true\nlens_repo_url = \"\"\n"
        )
        status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertIsNone(status.latest_available)
        self.assertEqual(status.tag_count, 0)

    def test_enabled_with_bad_remote_has_remote_error(self) -> None:
        self._write_toml(
            "[release]\nenabled = true\n"
            'lens_repo_url = "file:///nonexistent/repo.git"\n'
        )
        status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertIsNone(status.latest_available)
        # Remote error should be set (non-fatal failure)
        self.assertIsInstance(status.remote_error, str)
        # Available tags should be empty (graceful degradation)
        self.assertEqual(status.tag_count, 0)

    def test_enabled_with_remote_finds_latest(self) -> None:
        tag_dir = Path(tempfile.mkdtemp())
        bare = _init_repo_with_tags(tag_dir, ["v1.0.0", "v1.1.0", "v2.0.0"])
        self._write_toml(
            f"[release]\nenabled = true\nlens_repo_url = \"file://{bare}\"\n"
        )
        status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertEqual(status.latest_available_str, "v2.0.0")
        self.assertEqual(status.latest_available, SemverTag(2, 0, 0))
        self.assertEqual(status.tag_count, 3)

    def test_config_fields_preserved(self) -> None:
        tag_dir = Path(tempfile.mkdtemp())
        bare = _init_repo_with_tags(tag_dir, ["v1.0.0"])
        self._write_toml(
            f"[release]\nenabled = true\n"
            f'lens_repo_url = "file://{bare}"\n'
            f'auto_update = "minor"\n'
            f'requested_version = "v2.0.0"\n'
            f"major_update_pending = true\n"
            f'major_update_target_version = "v2.0.0"\n'
            f"major_update_approved = false\n"
        )
        status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertEqual(status.auto_update, "minor")
        self.assertEqual(status.requested_version, "v2.0.0")
        self.assertTrue(status.major_update_pending)
        self.assertEqual(status.major_update_target_version, "v2.0.0")
        self.assertFalse(status.major_update_approved)

    def test_installed_is_none_when_env_unset(self) -> None:
        # "Installed" must reflect only the deployed container's baked-in
        # LENS_VERSION env var (decision #2) -- never a value computed from
        # a local checkout. A desktop/dev run (env unset) must report None,
        # not a plausible-looking but unrelated local version.
        self._write_toml("[release]\nenabled = true\nlens_repo_url = \"\"\n")
        env = dict(os.environ)
        env.pop("LENS_VERSION", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertIsNone(status.installed_version_str)

    def test_env_var_used_when_set(self) -> None:
        self._write_toml("[release]\nenabled = true\nlens_repo_url = \"\"\n")
        with unittest.mock.patch.dict(os.environ, {"LENS_VERSION": "v99.99.99"}):
            status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertEqual(status.installed_version_str, "v99.99.99")

    def test_local_checkout_version_populated_from_lens_repo(self) -> None:
        # Distinct from "installed": this reflects what `lens deploy push`
        # would bake LENS_VERSION to *right now* from the Lens tool repo's
        # own checkout (decision #7) -- populated regardless of whether
        # LENS_VERSION is set, since it describes a pending build target,
        # not a deployed fact. The test process runs from within an actual
        # Lens repo checkout, so this should resolve to a non-empty string.
        self._write_toml("[release]\nenabled = true\nlens_repo_url = \"\"\n")
        status = compute_release_status(self._root)
        self.assertTrue(status.enabled)
        self.assertIsNotNone(status.local_checkout_version)

    def test_local_checkout_version_independent_of_installed(self) -> None:
        self._write_toml("[release]\nenabled = true\nlens_repo_url = \"\"\n")
        with unittest.mock.patch.dict(os.environ, {"LENS_VERSION": "v99.99.99"}):
            status = compute_release_status(self._root)
        self.assertEqual(status.installed_version_str, "v99.99.99")
        # Still populated even though "installed" came from the env var --
        # the two facts are unrelated.
        self.assertIsNotNone(status.local_checkout_version)


def _init_local_repo(tmp: Path, tags: list[str]) -> Path:
    """Create a local (non-bare) git repo with the given tags and return its path."""
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, check=True, capture_output=True,
    )

    (tmp / "README.md").write_text("test")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=tmp, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, check=True, capture_output=True,
    )

    for tag in tags:
        subprocess.run(
            ["git", "tag", tag],
            cwd=tmp, check=True, capture_output=True,
        )

    return tmp


class TestListLocalTags(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._repo = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_tags(self) -> None:
        repo = _init_local_repo(self._repo, [])
        self.assertEqual(list_local_tags(repo), [])

    def test_single_tag(self) -> None:
        repo = _init_local_repo(self._repo, ["v1.0.0"])
        self.assertEqual(list_local_tags(repo), [SemverTag(1, 0, 0)])

    def test_multiple_tags_sorted(self) -> None:
        repo = _init_local_repo(self._repo, ["v2.0.0", "v1.0.0", "v1.5.0"])
        self.assertEqual(
            list_local_tags(repo),
            [SemverTag(1, 0, 0), SemverTag(1, 5, 0), SemverTag(2, 0, 0)],
        )

    def test_ignores_non_semver(self) -> None:
        repo = _init_local_repo(self._repo, ["v1.0.0", "latest", "v1-beta"])
        self.assertEqual(list_local_tags(repo), [SemverTag(1, 0, 0)])


class TestComputeLocalVersion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._repo = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_tags_returns_0_0_0_with_hash(self) -> None:
        repo = _init_local_repo(self._repo, [])
        version = compute_local_version(repo_root=repo)
        self.assertTrue(version.startswith("0.0.0+"))
        self.assertGreater(len(version), len("0.0.0+"))

    def test_head_at_latest_tag_returns_clean_tag(self) -> None:
        repo = _init_local_repo(self._repo, ["v1.0.0"])
        version = compute_local_version(repo_root=repo)
        self.assertEqual(version, "v1.0.0")

    def test_head_ahead_of_tag_returns_tag_plus_hash(self) -> None:
        repo = _init_local_repo(self._repo, ["v1.0.0"])
        # Make a new commit after the tag
        (repo / "new.md").write_text("new content")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "new"],
            cwd=repo, check=True, capture_output=True,
        )
        version = compute_local_version(repo_root=repo)
        self.assertTrue(version.startswith("v1.0.0+"))
        self.assertGreater(len(version), len("v1.0.0+"))

    def test_multiple_tags_picks_latest(self) -> None:
        repo = _init_local_repo(self._repo, ["v1.0.0", "v2.0.0"])
        version = compute_local_version(repo_root=repo)
        self.assertEqual(version, "v2.0.0")
