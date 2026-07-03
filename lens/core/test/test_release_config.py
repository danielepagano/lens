"""Unit tests for release system configuration parsing and validation."""

from __future__ import annotations

import unittest

from lens.core.exceptions import LensException
from lens.core.release.config import (
    DatasetRepoConfig,
    ReleaseConfig,
    parse_dataset_repo_configs,
    parse_release_config,
    validate_deploy_topology,
    validate_git_url,
    validate_release_config,
)


class TestParseReleaseConfig(unittest.TestCase):
    def test_absent_returns_disabled_default(self) -> None:
        cfg = parse_release_config({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.auto_update, "off")
        self.assertEqual(cfg.lens_repo_url, "")

    def test_present_enabled(self) -> None:
        cfg = parse_release_config({"release": {"enabled": True, "lens_repo_url": "https://github.com/user/lens.git"}})
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.lens_repo_url, "https://github.com/user/lens.git")

    def test_all_fields_parsed(self) -> None:
        raw = {
            "release": {
                "enabled": True,
                "lens_repo_url": "git@github.com:user/lens.git",
                "auto_update": "minor",
                "requested_version": "v2.0.0",
                "major_update_pending": True,
                "major_update_target_version": "v2.0.0",
                "major_update_approved": False,
            }
        }
        cfg = parse_release_config(raw)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.lens_repo_url, "git@github.com:user/lens.git")
        self.assertEqual(cfg.auto_update, "minor")
        self.assertEqual(cfg.requested_version, "v2.0.0")
        self.assertTrue(cfg.major_update_pending)
        self.assertEqual(cfg.major_update_target_version, "v2.0.0")
        self.assertFalse(cfg.major_update_approved)

    def test_app_leader_defaults_false(self) -> None:
        cfg = parse_release_config({"release": {"enabled": True}})
        self.assertFalse(cfg.app_leader)

    def test_app_leader_parsed_true(self) -> None:
        cfg = parse_release_config({"release": {"enabled": True, "app_leader": True}})
        self.assertTrue(cfg.app_leader)

    def test_partial_fields_use_defaults(self) -> None:
        cfg = parse_release_config({"release": {"enabled": True, "lens_repo_url": "https://example.com/repo.git"}})
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.lens_repo_url, "https://example.com/repo.git")
        self.assertEqual(cfg.auto_update, "off")
        self.assertFalse(cfg.major_update_pending)
        self.assertEqual(cfg.major_update_target_version, "")
        self.assertFalse(cfg.major_update_approved)

    def test_wrong_type_ignored(self) -> None:
        cfg = parse_release_config({"release": "not a table"})
        self.assertFalse(cfg.enabled)


class TestParseDatasetRepoConfigs(unittest.TestCase):
    def test_absent_returns_empty(self) -> None:
        repos = parse_dataset_repo_configs({})
        self.assertEqual(repos, [])

    def test_single_repo_parsed(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [{"name": "lens-dnd", "git_url": "git@gitlab.com:org/lens-dnd.git"}]
        })
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].name, "lens-dnd")
        self.assertEqual(repos[0].git_url, "git@gitlab.com:org/lens-dnd.git")
        self.assertEqual(repos[0].ref, "main")

    def test_ref_defaults_to_main(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [{"name": "extra", "git_url": "https://example.com/extra.git"}]
        })
        self.assertEqual(repos[0].ref, "main")

    def test_ref_overridden(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [{"name": "extra", "git_url": "https://example.com/extra.git", "ref": "develop"}]
        })
        self.assertEqual(repos[0].ref, "develop")

    def test_missing_name_skipped(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [
                {"git_url": "https://example.com/noname.git"},
                {"name": "valid", "git_url": "https://example.com/valid.git"},
            ]
        })
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].name, "valid")

    def test_empty_ref_becomes_main(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [{"name": "x", "git_url": "https://example.com/x.git", "ref": "  "}]
        })
        self.assertEqual(repos[0].ref, "main")

    def test_not_a_list_returns_empty(self) -> None:
        repos = parse_dataset_repo_configs({"dataset_repo": "not-a-list"})
        self.assertEqual(repos, [])

    def test_filters_non_dict_entries(self) -> None:
        repos = parse_dataset_repo_configs({
            "dataset_repo": [
                {"name": "good", "git_url": "https://example.com/good.git"},
                42,
                "string",
            ]
        })
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].name, "good")


class TestValidateGitUrl(unittest.TestCase):
    def test_empty_returns_error(self) -> None:
        self.assertIsNotNone(validate_git_url(""))
        self.assertIsNotNone(validate_git_url("   "))

    def test_valid_ssh_scp_ok(self) -> None:
        self.assertIsNone(validate_git_url("git@github.com:org/repo.git"))

    def test_valid_ssh_scheme_ok(self) -> None:
        self.assertIsNone(validate_git_url("ssh://git@github.com/org/repo.git"))

    def test_valid_https_ok(self) -> None:
        self.assertIsNone(validate_git_url("https://github.com/org/repo.git"))

    def test_valid_https_with_dot_git_ok(self) -> None:
        self.assertIsNone(validate_git_url("https://gitlab.com/user/project.git"))

    def test_https_missing_host_error(self) -> None:
        err = validate_git_url("https:///path/to/repo")
        self.assertIsNotNone(err)
        self.assertIn("host", err or "")

    def test_https_missing_path_error(self) -> None:
        err = validate_git_url("https://github.com")
        self.assertIsNotNone(err)
        self.assertIn("path", err or "")

    def test_invalid_scheme_error(self) -> None:
        err = validate_git_url("ftp://github.com/repo.git")
        self.assertIsNotNone(err)

    def test_invalid_string_error(self) -> None:
        err = validate_git_url("not-a-url")
        self.assertIsNotNone(err)


class TestValidateReleaseConfig(unittest.TestCase):
    def test_disabled_returns_not_configured(self) -> None:
        cfg = ReleaseConfig(enabled=False)
        lines = validate_release_config(cfg, [], [])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][0], "ok")
        self.assertIn("not configured", lines[0][2])

    def test_enabled_ok(self) -> None:
        cfg = ReleaseConfig(
            enabled=True,
            lens_repo_url="https://github.com/user/lens.git",
            auto_update="minor",
        )
        lines = validate_release_config(cfg, [], [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertEqual(errors, [])

    def test_empty_lens_repo_url_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="")
        lines = validate_release_config(cfg, [], [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("lens_repo_url" in ln[1] for ln in errors))

    def test_invalid_lens_repo_url_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="not-a-valid-url")
        lines = validate_release_config(cfg, [], [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("lens_repo_url" in ln[1] for ln in errors))

    def test_invalid_auto_update_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git", auto_update="weekly")
        lines = validate_release_config(cfg, [], [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("auto_update" in ln[1] for ln in errors))

    def test_valid_auto_update_values(self) -> None:
        for val in ("off", "minor", "major"):
            cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git", auto_update=val)
            errors = [ln for ln in validate_release_config(cfg, [], []) if ln[0] == "error"]
            self.assertEqual([ln for ln in errors if "auto_update" in ln[1]], [], f"failed for {val}")

    def test_dataset_repo_missing_name_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [DatasetRepoConfig(name="", git_url="https://example.com/repo.git")]
        lines = validate_release_config(cfg, repos, [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("name" in ln[2] for ln in errors))

    def test_dataset_repo_empty_git_url_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [DatasetRepoConfig(name="test", git_url="")]
        lines = validate_release_config(cfg, repos, [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("git_url" in ln[2] for ln in errors))

    def test_dataset_repo_invalid_git_url_error(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [DatasetRepoConfig(name="test", git_url="not-a-url")]
        lines = validate_release_config(cfg, repos, [])
        errors = [ln for ln in lines if ln[0] == "error"]
        self.assertTrue(any("test" in ln[1] for ln in errors))

    def test_dataset_repo_name_not_in_datasets_warn(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [DatasetRepoConfig(name="my-extra", git_url="https://example.com/repo.git")]
        lines = validate_release_config(cfg, repos, ["rpg"])
        warns = [ln for ln in lines if ln[0] == "warn"]
        self.assertTrue(any("dataset_repo" in ln[1] for ln in warns))

    def test_dataset_repo_name_in_datasets_no_warn(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [DatasetRepoConfig(name="rpg", git_url="https://example.com/rpg.git")]
        lines = validate_release_config(cfg, repos, ["rpg"])
        warns = [ln for ln in lines if ln[0] == "warn"]
        self.assertEqual([ln for ln in warns if "dataset_repo" in ln[1]], [])

    def test_duplicate_dataset_repo_warn(self) -> None:
        cfg = ReleaseConfig(enabled=True, lens_repo_url="https://github.com/user/lens.git")
        repos = [
            DatasetRepoConfig(name="dup", git_url="https://example.com/a.git"),
            DatasetRepoConfig(name="dup", git_url="https://example.com/b.git"),
        ]
        lines = validate_release_config(cfg, repos, ["dup"])
        warns = [ln for ln in lines if ln[0] == "warn"]
        self.assertTrue(any("duplicate" in ln[2] for ln in warns))


class TestValidateDeployTopology(unittest.TestCase):
    def test_single_project_is_noop(self) -> None:
        cfg = ReleaseConfig(enabled=True, app_leader=False)
        # No leader, enabled=true, single project -- must not raise.
        validate_deploy_topology([("solo", cfg, [])])

    def test_empty_projects_is_noop(self) -> None:
        validate_deploy_topology([])

    def test_multi_project_no_release_is_ok(self) -> None:
        a = ReleaseConfig()
        b = ReleaseConfig()
        validate_deploy_topology([("a", a, []), ("b", b, [])])

    def test_exactly_one_leader_ok(self) -> None:
        leader = ReleaseConfig(enabled=True, app_leader=True)
        sibling = ReleaseConfig(enabled=False, app_leader=False)
        validate_deploy_topology([("a", leader, []), ("b", sibling, [])])

    def test_two_leaders_raises(self) -> None:
        a = ReleaseConfig(enabled=True, app_leader=True)
        b = ReleaseConfig(enabled=True, app_leader=True)
        with self.assertRaises(LensException) as ctx:
            validate_deploy_topology([("a", a, []), ("b", b, [])])
        self.assertIn("app_leader", str(ctx.exception))
        self.assertIn("a", str(ctx.exception))
        self.assertIn("b", str(ctx.exception))

    def test_non_leader_enabled_raises(self) -> None:
        leader = ReleaseConfig(enabled=True, app_leader=True)
        non_leader = ReleaseConfig(enabled=True, app_leader=False)
        with self.assertRaises(LensException) as ctx:
            validate_deploy_topology([("leader", leader, []), ("sibling", non_leader, [])])
        self.assertIn("sibling", str(ctx.exception))

    def test_dataset_repo_agreement_ok(self) -> None:
        repo_a = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/x.git", ref="main")
        repo_b = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/x.git", ref="main")
        validate_deploy_topology([
            ("a", ReleaseConfig(), [repo_a]),
            ("b", ReleaseConfig(), [repo_b]),
        ])

    def test_dataset_repo_conflict_git_url_raises(self) -> None:
        repo_a = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/x.git", ref="main")
        repo_b = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/y.git", ref="main")
        with self.assertRaises(LensException) as ctx:
            validate_deploy_topology([
                ("a", ReleaseConfig(), [repo_a]),
                ("b", ReleaseConfig(), [repo_b]),
            ])
        self.assertIn("shared", str(ctx.exception))

    def test_dataset_repo_conflict_ref_raises(self) -> None:
        repo_a = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/x.git", ref="main")
        repo_b = DatasetRepoConfig(name="shared", git_url="git@gitlab.com:org/x.git", ref="dev")
        with self.assertRaises(LensException):
            validate_deploy_topology([
                ("a", ReleaseConfig(), [repo_a]),
                ("b", ReleaseConfig(), [repo_b]),
            ])

    def test_three_projects_one_leader_ok(self) -> None:
        leader = ReleaseConfig(enabled=True, app_leader=True)
        sibling = ReleaseConfig()
        validate_deploy_topology([
            ("a", leader, []),
            ("b", sibling, []),
            ("c", sibling, []),
        ])
