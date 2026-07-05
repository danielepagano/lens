"""Tests for deploy/ci/release_secrets.py (standalone CI script).

Exercises the script as a subprocess with no dependency on the lens
package, matching its actual deployment environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_SCRIPT = str(Path(__file__).parents[3] / "deploy" / "ci" / "release_secrets.py")


def _run(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged: dict[str, str] = {
        k: v for k, v in os.environ.items() if k != "PYTHONPATH"
    }
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, _SCRIPT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged,
    )


def _init_project(base: Path, lens_toml: str) -> Path:
    """Create a throwaway git repo with a lens.toml and a first commit."""
    project = base / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project, check=True, capture_output=True,
    )
    (project / "lens.toml").write_text(lens_toml)
    subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=project, check=True, capture_output=True,
    )
    # Add a bare remote so sync commands can call git remote get-url origin
    remote = base / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=project, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=project, check=True, capture_output=True,
    )
    return project



def _head_sha(project: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


class ReleaseSecretsCheckTests(unittest.TestCase):
    """Tests for ``release_secrets.py check`` (secrets pre-flight)."""

    def test_check_disabled_release_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(Path(tmp), "")
            rp = _run("check", "--json", cwd=project)
            self.assertNotEqual(rp.returncode, 0)

    def test_check_basic_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp), '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"'
            )
            rp = _run("check", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)
            data = json.loads(rp.stdout)
            self.assertIn("leader_slug", data)
            self.assertIn("secrets", data)
            self.assertIn("FLY_API_TOKEN", {s["name"] for s in data["secrets"]})

    def test_check_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp), '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"'
            )
            rp = _run("check", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)
            self.assertIn("Release secrets check", rp.stdout)


class ReleaseCheckReleaseTests(unittest.TestCase):
    """Tests for ``release_secrets.py check-release`` (parent-hash check)."""

    def test_disabled_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(Path(tmp), "")
            rp = _run("check-release", "--since", "HEAD", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0)
            data = json.loads(rp.stdout)
            self.assertEqual(data["action"], "none")

    def test_no_version_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp), '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"'
            )
            rp = _run("check-release", "--since", "HEAD", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0)
            data = json.loads(rp.stdout)
            self.assertEqual(data["action"], "none")

    def test_no_from_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                'requested_version = "v1.0.0"\n',
            )
            rp = _run("check-release", "--since", "HEAD", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0)
            data = json.loads(rp.stdout)
            self.assertEqual(data["action"], "none")

    def test_parent_match_returns_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                'requested_version = "v1.0.0"\n',
            )
            first_sha = _head_sha(project)

            # Record the request (requested_from_commit = first commit)
            lens_toml = project / "lens.toml"
            raw = lens_toml.read_text() + f'requested_from_commit = "{first_sha}"\n'
            lens_toml.write_text(raw)
            subprocess.run(["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "record-request"],
                cwd=project, check=True, capture_output=True,
            )

            # since = first commit SHA, so range is first_sha..HEAD
            # The second commit has first_sha as parent — match!
            rp = _run("check-release", "--since", first_sha, "--json", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)
            data = json.loads(rp.stdout)
            self.assertEqual(data["action"], "apply")
            self.assertEqual(data["target"], "v1.0.0")

    def test_no_parent_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                'requested_version = "v2.0.0"\n',
            )
            head = _head_sha(project)
            # requested_from_commit = init commit SHA, but --since is also HEAD
            # so range is HEAD..HEAD (empty) — no parents to match
            lens_toml = project / "lens.toml"
            lens_toml.write_text(
                lens_toml.read_text() + f'requested_from_commit = "{head}"\n',
            )
            subprocess.run(
                ["git", "add", "lens.toml"], cwd=project, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "record-request"],
                cwd=project, check=True, capture_output=True,
            )

            # since = HEAD after the request commit — range is empty
            rp = _run("check-release", "--since", _head_sha(project), "--json", cwd=project)
            self.assertEqual(rp.returncode, 0)
            data = json.loads(rp.stdout)
            self.assertEqual(data["action"], "none")

    def test_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                'requested_version = "v1.0.0"\nrequested_from_commit = "abc"\n',
            )
            rp = _run("check-release", "--since", "HEAD", cwd=project)
            self.assertEqual(rp.returncode, 0)
            self.assertIn("action:", rp.stdout)

    def test_invalid_semver_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                'requested_version = "not-a-version"\nrequested_from_commit = "abc"\n',
            )
            rp = _run("check-release", "--since", "HEAD", cwd=project)
            self.assertNotEqual(rp.returncode, 0)


class ReleaseApplyTests(unittest.TestCase):
    """Tests for ``release_secrets.py apply`` (build-param validation)."""

    def test_disabled_release_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(Path(tmp), "")
            rp = _run("apply", "--to", "v1.0.0", "--json", cwd=project)
            self.assertNotEqual(rp.returncode, 0)

    def test_missing_lens_repo_url_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp), '[release]\nenabled = true\n'
            )
            rp = _run("apply", "--to", "v1.0.0", "--json", cwd=project)
            self.assertNotEqual(rp.returncode, 0)

    def test_invalid_tag_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp), '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
            )
            rp = _run("apply", "--to", "bad-tag", "--json", cwd=project)
            self.assertNotEqual(rp.returncode, 0)

    def test_valid_apply_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://github.com/x/lens.git"\n',
            )
            rp = _run("apply", "--to", "v1.2.3", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)
            data = json.loads(rp.stdout)
            self.assertEqual(data["lens_repo_url"], "https://github.com/x/lens.git")
            self.assertEqual(data["tag"], "v1.2.3")

    def test_tag_without_v_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://github.com/x/lens.git"\n',
            )
            rp = _run("apply", "--to", "1.2.3", "--json", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)
            data = json.loads(rp.stdout)
            self.assertEqual(data["tag"], "1.2.3")

    def test_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://github.com/x/lens.git"\n',
            )
            rp = _run("apply", "--to", "v1.0.0", cwd=project)
            self.assertEqual(rp.returncode, 0)
            self.assertIn("lens_repo_url:", rp.stdout)

    def test_missing_to_flag_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://github.com/x/lens.git"\n',
            )
            rp = _run("apply", cwd=project)
            self.assertNotEqual(rp.returncode, 0)


class ReleaseSecretsSyncTests(unittest.TestCase):
    """Tests for ``release_secrets.py sync`` (topology + secret sync)."""

    def test_disabled_release_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(Path(tmp), "")
            rp = _run("sync", "--dry-run", "--fly-app", "myapp", cwd=project)
            self.assertNotEqual(rp.returncode, 0)

    def test_sync_dry_run_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n'
                '[[llm]]\napi_key_env = "MY_KEY"\nmodel = "gpt-4"\n',
            )
            with self.subTest("without env var — collects project-level secrets only"):
                rp = _run("sync", "--dry-run", "--fly-app", "myapp", cwd=project)
                self.assertEqual(rp.returncode, 0, msg=rp.stderr)
                self.assertIn("synced ", rp.stdout)

            with self.subTest("with env var — includes api key"):
                rp = _run("sync", "--dry-run", "--fly-app", "myapp", cwd=project,
                          env={"MY_KEY": "sk-test"})
                self.assertEqual(rp.returncode, 0, msg=rp.stderr)
                # More secrets when the LLM api_key_env var is set
                no_key = _run("sync", "--dry-run", "--fly-app", "myapp", cwd=project)
                self.assertNotEqual(
                    rp.stdout.strip(), no_key.stdout.strip(),
                    msg="output should differ when MY_KEY is set",
                )

    def test_fly_app_auto_detected_from_fly_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _init_project(
                Path(tmp),
                '[release]\nenabled = true\nlens_repo_url = "https://x.com/x.git"\n',
            )
            (project / "fly.toml").write_text('app = "my-auto-app"\n')
            rp = _run("sync", "--dry-run", cwd=project)
            self.assertEqual(rp.returncode, 0, msg=rp.stderr)


class UnknownCommandTests(unittest.TestCase):
    def test_unknown_command_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rp = _run("nonsense", cwd=Path(tmp))
            self.assertNotEqual(rp.returncode, 0)

    def test_no_args_shows_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rp = _run(cwd=Path(tmp))
            self.assertNotEqual(rp.returncode, 0)
            self.assertIn("Usage", rp.stderr)


if __name__ == "__main__":
    unittest.main()
