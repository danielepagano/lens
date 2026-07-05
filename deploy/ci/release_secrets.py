#!/usr/bin/env python3
"""Standalone check/sync for CI release pipelines.

Usage:
    python3 release_secrets.py check [--fly] [--json]
    python3 release_secrets.py check-release --since <sha> [--json]
    python3 release_secrets.py apply --to <tag> [--json]
    python3 release_secrets.py sync [--fly-app <name>] [--dry-run]

Zero dependencies beyond Python 3.11+ stdlib (uses ``tomllib``).
Copy alongside ``release.sh`` in your project repo — nothing from the
Lens package is needed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


# ── config dataclasses ──────────────────────────────────────────────────
# Canonical source: lens.core.release.config.
# When run inside the Lens venv (tests, UI), import from there.
# When standalone in CI (no lens package), fall back to inline copies.

try:
    from lens.core.release.config import (
        DatasetRepoConfig,
        DependentProjectConfig,
        ReleaseConfig,
        parse_dataset_repo_configs,
        parse_dependent_project_configs,
        parse_release_config,
    )
except ImportError:

    @dataclass(frozen=True)
    class ReleaseConfig:
        enabled: bool = False
        lens_repo_url: str = ""
        requested_version: str = ""
        requested_from_commit: str = ""
        app_leader: bool = False

    @dataclass(frozen=True)
    class DatasetRepoConfig:
        name: str
        git_url: str
        ref: str = "main"

    @dataclass(frozen=True)
    class DependentProjectConfig:
        name: str
        git_url: str
        ref: str = "main"

    def parse_release_config(raw_config: dict[str, Any]) -> ReleaseConfig:
        raw = raw_config.get("release")
        if not isinstance(raw, dict):
            return ReleaseConfig()
        raw_dict = cast(dict[str, Any], raw)
        kwargs: dict[str, Any] = {}
        for field_name in (
            "enabled", "lens_repo_url", "requested_version",
            "requested_from_commit", "app_leader",
        ):
            val = raw_dict.get(field_name)
            if val is not None:
                kwargs[field_name] = val
        return ReleaseConfig(**kwargs)

    def parse_dependent_project_configs(raw_config: dict[str, Any]) -> list[DependentProjectConfig]:
        raw_list = raw_config.get("dependent_project", [])
        if not isinstance(raw_list, list):
            return []
        typed_list = cast(list[Any], raw_list)
        result: list[DependentProjectConfig] = []
        for raw_entry in typed_list:
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            git_url = entry.get("git_url", "")
            if not isinstance(git_url, str):
                continue
            ref = entry.get("ref", "main")
            if not isinstance(ref, str):
                ref = "main"
            result.append(
                DependentProjectConfig(
                    name=name.strip(),
                    git_url=git_url.strip(),
                    ref=ref.strip() if ref.strip() else "main",
                )
            )
        return result

    def parse_dataset_repo_configs(raw_config: dict[str, Any]) -> list[DatasetRepoConfig]:
        raw_list = raw_config.get("dataset_repo", [])
        if not isinstance(raw_list, list):
            return []
        typed_list = cast(list[Any], raw_list)
        result: list[DatasetRepoConfig] = []
        for raw_entry in typed_list:
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            git_url = entry.get("git_url", "")
            if not isinstance(git_url, str):
                continue
            ref = entry.get("ref", "main")
            if not isinstance(ref, str):
                ref = "main"
            result.append(
                DatasetRepoConfig(
                    name=name.strip(),
                    git_url=git_url.strip(),
                    ref=ref.strip() if ref.strip() else "main",
                )
            )
        return result


# ── semver ───────────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\+.*)?$")


def _parse_semver_tag(ref: str) -> tuple[int, int, int] | None:
    """Parse a vMAJOR.MINOR.PATCH tag into a (major, minor, patch) tuple.

    Accepts with or without leading ``v``, strips build metadata.
    Returns ``None`` on failure.
    """
    m = _SEMVER_RE.match(ref.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ── helpers ─────────────────────────────────────────────────────────────


def _slug_to_env_key(slug: str) -> str:
    return slug.upper().replace("-", "_")


def _read_lens_toml(project_root: Path) -> dict[str, Any]:
    path = project_root / "lens.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


def _git_clone(git_url: str, dest: Path, ref: str = "main") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, git_url, str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"git clone {git_url} failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def _read_fly_app(project_root: Path) -> str | None:
    fly_toml = project_root / "fly.toml"
    if not fly_toml.exists():
        return None
    try:
        with fly_toml.open("rb") as f:
            cfg = tomllib.load(f)
        app = cfg.get("app")
        return str(app) if isinstance(app, str) and app.strip() else None
    except Exception:
        return None


def _git_rev_list_parents(project_root: Path, since: str | None) -> list[str]:
    """Return the parent commit SHAs for the range ``since..HEAD``.

    When *since* is ``None``, returns only HEAD's first parent.
    """
    if since is None:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"git rev-parse HEAD failed: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        head = result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", f"{head}^1"],
            cwd=project_root, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        return [result.stdout.strip()]

    cmd = ["git", "rev-list", "--parents", f"{since}..HEAD"]
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"git rev-list --parents {since}..HEAD failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    parents: list[str] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            parents.extend(parts[1:])
    return parents


def _list_fly_secrets(fly_app: str) -> set[str]:
    try:
        result = subprocess.run(
            ["flyctl", "secrets", "list", "--app", fly_app],
            capture_output=True, text=True, check=True,
        )
        names: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if parts and not parts[0].startswith("NAME"):
                names.add(parts[0])
        return names
    except Exception:
        return set()


# ── secrets check ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class SecretRequirement:
    name: str
    source: str
    set_in_env: bool
    set_on_fly: bool | None = None


@dataclass(frozen=True)
class ReleaseSecretsCheckResult:
    leader_slug: str
    fly_app: str | None
    project_slugs: list[str]
    dependent_projects: list[DependentProjectConfig]
    dataset_repos: list[DatasetRepoConfig]
    secrets: list[SecretRequirement]


def execute_release_secrets_check(
    project_root: Path, *, check_fly: bool = False,
) -> ReleaseSecretsCheckResult:
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        print("release is not enabled in lens.toml", file=sys.stderr)
        sys.exit(1)

    dependents = parse_dependent_project_configs(raw)
    dataset_repos = parse_dataset_repo_configs(raw)
    leader_slug = project_root.name
    fly_app = _read_fly_app(project_root)

    fly_secrets: set[str] = set()
    if check_fly and fly_app:
        fly_secrets = _list_fly_secrets(fly_app)

    secrets: list[SecretRequirement] = []
    seen_api_keys: set[str] = set()
    all_configs: list[tuple[str, dict[str, Any]]] = [(leader_slug, raw)]
    temp_clone_dirs: list[Path] = []

    try:
        for dep in dependents:
            clone_dir = Path(tempfile.mkdtemp(prefix=f"lens-secrets-{dep.name}-")) / dep.name
            _git_clone(dep.git_url, clone_dir, dep.ref)
            dep_raw = _read_lens_toml(clone_dir)
            all_configs.append((dep.name, dep_raw))
            temp_clone_dirs.append(clone_dir.parent)

        for slug, config in all_configs:
            for table_key in ("llm", "image", "speech"):
                raw_list = config.get(table_key, [])
                entries = cast(list[Any], raw_list) if isinstance(raw_list, list) else []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry_cfg = cast(dict[str, Any], entry)
                    env_name = cast(str | None, entry_cfg.get("api_key_env"))
                    if not isinstance(env_name, str) or env_name in seen_api_keys:
                        continue
                    seen_api_keys.add(env_name)
                    provider = cast(str | None, entry_cfg.get("provider", "?"))
                    secrets.append(SecretRequirement(
                        name=env_name,
                        source=f"{table_key}: {provider}" + (f" ({slug})" if slug != leader_slug else ""),
                        set_in_env=env_name in os.environ,
                        set_on_fly=env_name in fly_secrets if check_fly else None,
                    ))

        for slug, _config in all_configs:
            env_key = _slug_to_env_key(slug)
            key_var = f"GIT_REPO_DEPLOY_KEY_{env_key}"
            tag = "project" if slug == leader_slug else "dependent_project"
            secrets.append(SecretRequirement(
                name=key_var,
                source=f"{tag}: {slug}",
                set_in_env=key_var in os.environ,
                set_on_fly=key_var in fly_secrets if check_fly else None,
            ))

        for repo in dataset_repos:
            ds_env_key = repo.name.upper().replace("-", "_")
            ds_key_var = f"DATASET_REPO_DEPLOY_KEY_{ds_env_key}"
            secrets.append(SecretRequirement(
                name=ds_key_var,
                source=f"dataset_repo: {repo.name}",
                set_in_env=ds_key_var in os.environ,
                set_on_fly=ds_key_var in fly_secrets if check_fly else None,
            ))

        secrets.append(SecretRequirement(
            name="FLY_API_TOKEN",
            source="flyctl deploy auth",
            set_in_env="FLY_API_TOKEN" in os.environ,
        ))

        project_slugs = [leader_slug] + [d.name for d in dependents]

        return ReleaseSecretsCheckResult(
            leader_slug=leader_slug,
            fly_app=fly_app,
            project_slugs=project_slugs,
            dependent_projects=dependents,
            dataset_repos=dataset_repos,
            secrets=secrets,
        )
    finally:
        for tmp_dir in temp_clone_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── check-release ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReleaseCheckResult:
    action: str  # "none" | "apply"
    target: str | None = None
    summary: str = ""


def execute_release_check(project_root: Path, since: str | None = None) -> ReleaseCheckResult:
    """Check whether the push should trigger a release.

    Reads ``[release] requested_version`` and ``requested_from_commit``
    from the project's ``lens.toml``.  When *since* is provided, checks
    every commit in ``since..HEAD`` — if any has ``requested_from_commit``
    as its parent, returns ``"apply"`` with the target tag.
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        return ReleaseCheckResult(action="none", summary="release system not enabled")

    requested = cfg.requested_version.strip()
    if not requested:
        return ReleaseCheckResult(action="none", summary="no version requested")

    sanity = _parse_semver_tag(requested)
    if sanity is None:
        print(f"requested_version {requested!r} is not a valid vMAJOR.MINOR.PATCH tag", file=sys.stderr)
        sys.exit(1)

    from_commit = cfg.requested_from_commit.strip()
    if not from_commit:
        return ReleaseCheckResult(action="none", summary="requested_from_commit is empty")

    parents = _git_rev_list_parents(project_root, since)
    if from_commit in parents:
        return ReleaseCheckResult(
            action="apply",
            target=f"v{sanity[0]}.{sanity[1]}.{sanity[2]}",
            summary=f"parent match on {from_commit}; deploy v{sanity[0]}.{sanity[1]}.{sanity[2]}",
        )

    return ReleaseCheckResult(
        action="none",
        summary=f"no commit in range has {from_commit} as parent",
    )


# ── apply ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReleaseApplyResult:
    lens_repo_url: str
    tag: str
    summary: str


def execute_release_apply(project_root: Path, target_tag: str) -> ReleaseApplyResult:
    """Validate config and return build parameters for the requested tag.

    **No git writes occur.**
    """
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        print("release system is not enabled", file=sys.stderr)
        sys.exit(1)
    url = cfg.lens_repo_url.strip()
    if not url:
        print("[release].lens_repo_url must be set", file=sys.stderr)
        sys.exit(1)
    normalized_tag = target_tag.strip()
    target_semver = _parse_semver_tag(normalized_tag)
    if target_semver is None:
        print("--to must be a valid vMAJOR.MINOR.PATCH tag", file=sys.stderr)
        sys.exit(1)

    return ReleaseApplyResult(
        lens_repo_url=url,
        tag=normalized_tag,
        summary=f"release apply target {normalized_tag}",
    )


# ── secrets sync ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReleaseSecretsSyncResult:
    status: str
    secrets_set: int
    summary: str
    collected_secrets: dict[str, str] = field(default_factory=lambda: {})


def _collect_ci_available_api_keys(
    config: dict[str, Any], table_key: str, seen: set[str], into: dict[str, str],
) -> None:
    raw_list = config.get(table_key, [])
    entries = cast(list[Any], raw_list) if isinstance(raw_list, list) else []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        env_name = entry.get("api_key_env")
        if not isinstance(env_name, str) or env_name in seen:
            continue
        seen.add(env_name)
        value = os.environ.get(env_name)
        if value:
            into[env_name] = value


def _get_git_remote_url(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=project_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"failed to get git remote URL: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _fly_secrets_set(fly_app: str, secrets: dict[str, str]) -> None:
    args = ["flyctl", "secrets", "set", "--app", fly_app]
    for key, value in secrets.items():
        args.append(f"{key}={value}")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"fly secrets set failed: {result.stderr.strip() or result.stdout.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)


def execute_release_secrets_sync(
    project_root: Path, fly_app: str, dry_run: bool = False,
) -> ReleaseSecretsSyncResult:
    raw = _read_lens_toml(project_root)
    cfg = parse_release_config(raw)
    if not cfg.enabled:
        print("release is not enabled in lens.toml", file=sys.stderr)
        sys.exit(1)

    dependents = parse_dependent_project_configs(raw)
    leader_slug = project_root.name

    all_projects: list[tuple[str, Path, dict[str, Any]]] = [(leader_slug, project_root, raw)]
    temp_clone_dirs: list[Path] = []

    try:
        for dep in dependents:
            clone_dir = Path(tempfile.mkdtemp(prefix=f"lens-secrets-{dep.name}-")) / dep.name
            _git_clone(dep.git_url, clone_dir, dep.ref)
            dep_raw = _read_lens_toml(clone_dir)
            all_projects.append((dep.name, clone_dir, dep_raw))
            temp_clone_dirs.append(clone_dir.parent)

        secrets: dict[str, str] = {}
        seen_api_keys: set[str] = set()

        for _slug, _proj_root, proj_raw in all_projects:
            _collect_ci_available_api_keys(proj_raw, "llm", seen_api_keys, secrets)
            _collect_ci_available_api_keys(proj_raw, "image", seen_api_keys, secrets)
            _collect_ci_available_api_keys(proj_raw, "speech", seen_api_keys, secrets)

        for slug, proj_root, _proj_raw in all_projects:
            env_key = _slug_to_env_key(slug)
            deploy_key_var = f"GIT_REPO_DEPLOY_KEY_{env_key}"
            val = os.environ.get(deploy_key_var)
            if val:
                secrets[deploy_key_var] = val

        for slug, proj_root, _proj_raw in all_projects:
            env_key = _slug_to_env_key(slug)
            if slug == leader_slug:
                url = _get_git_remote_url(proj_root)
            else:
                dep = next(d for d in dependents if d.name == slug)
                url = dep.git_url
            secrets[f"PROJECT_REPO_URL_{env_key}"] = url

        seen_datasets: set[str] = set()
        for _slug, _proj_root, proj_raw in all_projects:
            for repo in parse_dataset_repo_configs(proj_raw):
                if repo.name in seen_datasets:
                    continue
                seen_datasets.add(repo.name)
                env_key = repo.name.upper().replace("-", "_")
                var_name = f"DATASET_REPO_DEPLOY_KEY_{env_key}"
                val = os.environ.get(var_name)
                if val:
                    secrets[var_name] = val

        slugs = [leader_slug] + [d.name for d in dependents]
        secrets["LENS_PROJECT_SLUGS"] = ",".join(slugs)

        if not dry_run and secrets:
            _fly_secrets_set(fly_app, secrets)

        return ReleaseSecretsSyncResult(
            status="ok",
            secrets_set=len(secrets),
            summary=f"synced {len(secrets)} secrets to Fly app {fly_app}",
            collected_secrets=secrets,
        )
    finally:
        for tmp_dir in temp_clone_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── CLI subcommands ─────────────────────────────────────────────────────


def cmd_check(args: list[str]) -> None:
    fly = "--fly" in args
    json_output = "--json" in args
    cwd = Path.cwd()

    result = execute_release_secrets_check(cwd, check_fly=fly)

    if json_output:
        payload = {
            "leader_slug": result.leader_slug,
            "fly_app": result.fly_app,
            "project_slugs": result.project_slugs,
            "secrets": [
                {
                    "name": s.name,
                    "source": s.source,
                    "set_in_env": s.set_in_env,
                    "set_on_fly": s.set_on_fly,
                }
                for s in result.secrets
            ],
        }
        print(json.dumps(payload))
        return

    print(f"Release secrets check for app: {result.fly_app or '(unknown)'}")
    print()
    print(f"  Leader:     {result.leader_slug}")
    if result.dependent_projects:
        print("  Dependents: " + ", ".join(d.name for d in result.dependent_projects))
    if result.dataset_repos:
        print("  Datasets:   " + ", ".join(r.name for r in result.dataset_repos))
    print()

    env_count = 0
    fly_ok = 0
    fly_total = 0
    for s in result.secrets:
        env_sym = "✓" if s.set_in_env else "✗"
        if s.set_in_env:
            env_count += 1
        fly_sym = "✓" if s.set_on_fly else "✗" if s.set_on_fly is False else "—"
        if s.set_on_fly is not None:
            fly_total += 1
            if s.set_on_fly:
                fly_ok += 1
        print(f"  {s.name:<45} {s.source:<30} {env_sym:<5} {fly_sym:<5}")

    print()
    print(f"  {env_count}/{len(result.secrets)} secrets set in environment")
    if fly_total:
        print(f"  {fly_ok}/{fly_total} checkable secrets set on Fly")
    if not fly:
        print()
        print("  Tip: pass --fly to also check which secrets are set on the Fly app.")


def cmd_sync(args: list[str]) -> None:
    fly_app = ""
    dry_run = False
    i = 0
    while i < len(args):
        if args[i] == "--fly-app" and i + 1 < len(args):
            fly_app = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            i += 1

    if not fly_app:
        detected = _read_fly_app(Path.cwd())
        if detected:
            fly_app = detected
        else:
            print("sync: --fly-app is required (no fly.toml found)", file=sys.stderr)
            sys.exit(1)

    result = execute_release_secrets_sync(Path.cwd(), fly_app, dry_run=dry_run)
    print(result.summary)


def cmd_check_release(args: list[str]) -> None:
    since: str | None = None
    json_output = "--json" in args

    i = 0
    while i < len(args):
        if args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif args[i] == "--json":
            i += 1
        else:
            i += 1

    result = execute_release_check(Path.cwd(), since=since)
    if json_output:
        print(json.dumps({
            "action": result.action,
            "target": result.target,
            "summary": result.summary,
        }))
    else:
        print(f"action: {result.action}")
        if result.target:
            print(f"target: {result.target}")
        print(f"summary: {result.summary}")


def cmd_apply(args: list[str]) -> None:
    target_tag = ""
    json_output = "--json" in args

    i = 0
    while i < len(args):
        if args[i] == "--to" and i + 1 < len(args):
            target_tag = args[i + 1]
            i += 2
        elif args[i] == "--json":
            i += 1
        else:
            i += 1

    if not target_tag:
        print("apply: --to <tag> is required", file=sys.stderr)
        sys.exit(1)

    result = execute_release_apply(Path.cwd(), target_tag)
    if json_output:
        print(json.dumps({
            "lens_repo_url": result.lens_repo_url,
            "tag": result.tag,
            "summary": result.summary,
        }))
    else:
        print(f"lens_repo_url: {result.lens_repo_url}")
        print(f"tag: {result.tag}")
        print(f"summary: {result.summary}")


# ── entry point ─────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: release_secrets.py <check|check-release|apply|sync> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    command = args[0]
    rest = args[1:]

    if command == "check":
        cmd_check(rest)
    elif command == "check-release":
        cmd_check_release(rest)
    elif command == "apply":
        cmd_apply(rest)
    elif command == "sync":
        cmd_sync(rest)
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
