"""Release system configuration parsing and validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from lens.core.exceptions import LensException
from lens.core.git_ssh_remote import parse_git_ssh_remote


@dataclass(frozen=True)
class ReleaseConfig:
    enabled: bool = False
    lens_repo_url: str = ""
    requested_version: str = ""
    requested_from_commit: str = ""
    # Only meaningful when this project's Fly app also serves sibling
    # projects (parent-of-projects `fly.toml` topology). Ignored for
    # single-project apps, where the sole served project is trivially the
    # leader. In a multi-project app, exactly one served project must set
    # this true; that project's `[release]` table is authoritative for the
    # whole Fly app.
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


def parse_dependent_project_configs(raw_config: dict[str, Any]) -> list[DependentProjectConfig]:
    """Parse ``[[dependent_project]]`` from a parsed ``lens.toml`` dict."""
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


def parse_release_config(raw_config: dict[str, Any]) -> ReleaseConfig:
    """Parse ``[release]`` from a parsed ``lens.toml`` dict.

    Returns a default (disabled) ``ReleaseConfig`` when the section is absent.
    """
    raw = raw_config.get("release")
    if not isinstance(raw, dict):
        return ReleaseConfig()
    raw_dict = cast(dict[str, Any], raw)
    kwargs: dict[str, Any] = {}
    for field_name in (
        "enabled",
        "lens_repo_url",
        "requested_version",
        "requested_from_commit",
        "app_leader",
    ):
        val = raw_dict.get(field_name)
        if val is not None:
            kwargs[field_name] = val
    return ReleaseConfig(**kwargs)


def parse_dataset_repo_configs(raw_config: dict[str, Any]) -> list[DatasetRepoConfig]:
    """Parse ``[[dataset_repo]]`` from a parsed ``lens.toml`` dict."""
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


def validate_git_url(url: str) -> str | None:
    """Return an error message if *url* is not a valid SSH or HTTPS git URL, or ``None``."""
    u = url.strip()
    if not u:
        return "git URL is empty"
    lowered = u.lower()
    if lowered.startswith(("https://", "http://")):
        parsed = urlparse(u)
        if not parsed.hostname:
            return "missing host in git URL"
        if not parsed.path or parsed.path == "/":
            return "missing repository path in git URL"
        return None
    try:
        parse_git_ssh_remote(u)
    except ValueError as exc:
        return str(exc)
    return None


def validate_release_config(
    config: ReleaseConfig,
    dataset_repos: list[DatasetRepoConfig],
    project_dataset_names: list[str],
    dependent_projects: list[DependentProjectConfig] | None = None,
) -> list[tuple[str, str, str]]:
    """Validate release configuration.

    Returns ``[(severity, topic, detail), ...]`` suitable for feeding into
    ``ProjectCheckResult.add``.
    """
    lines: list[tuple[str, str, str]] = []
    if not config.enabled:
        lines.append(("ok", "release", "not configured"))
        return lines

    lines.append(("ok", "release", "configured"))

    if not config.lens_repo_url.strip():
        lines.append(("error", "release lens_repo_url", "must be set when [release] is present"))
    else:
        err = validate_git_url(config.lens_repo_url)
        if err:
            lines.append(("error", "release lens_repo_url", err))

    if dependent_projects:
        seen_dep_names: set[str] = set()
        for dep in dependent_projects:
            if dep.name in seen_dep_names:
                lines.append(("warn", f"dependent_project {dep.name}", "duplicate name"))
            seen_dep_names.add(dep.name)
            err = validate_git_url(dep.git_url)
            if err:
                lines.append(("error", f"dependent_project {dep.name}", err))

    seen_names: set[str] = set()
    for repo in dataset_repos:
        if not repo.name:
            lines.append(("error", "dataset_repo", "name must be a non-empty string"))
            continue

        if repo.name in seen_names:
            lines.append(("warn", f"dataset_repo {repo.name}", "duplicate name"))
        seen_names.add(repo.name)

        if not repo.git_url.strip():
            lines.append(("error", f"dataset_repo {repo.name}", "git_url is required"))
        else:
            err = validate_git_url(repo.git_url)
            if err:
                lines.append(("error", f"dataset_repo {repo.name}", err))

        if repo.name not in project_dataset_names:
            lines.append(
                (
                    "warn",
                    f"dataset_repo {repo.name}",
                    "name does not match any entry in [project] datasets",
                )
            )

    return lines


def validate_deploy_topology(
    project_configs: list[tuple[str, ReleaseConfig, list[DatasetRepoConfig]]],
) -> None:
    """Validate cross-project consistency for a Fly app serving multiple projects.

    *project_configs* is ``[(slug, release_config, dataset_repos), ...]`` for
    every project sharing one Fly app (the parent-of-projects ``fly.toml``
    topology documented in ``deploy/README.md``). Callers should skip this
    entirely for single-project apps — a lone project is trivially the
    leader and there's nothing cross-project to reconcile.

    Raises :class:`LensException` (never returns a value) when:

    - more than one project sets ``[release] app_leader = true`` — only one
      project may govern the Lens version for a shared Fly app;
    - any project has ``[release] enabled = true`` while not being the
      designated leader — release automation only ever runs from the
      leader's own `lens.toml`/CI pipeline;
    - two projects declare a ``[[dataset_repo]]`` with the same ``name`` but
      a different ``git_url``/``ref`` — they would race for the same shared
      clone on the Fly volume.

    Does *not* require a leader to exist — a multi-project deployment that
    doesn't use the release system at all is valid. Callers that need to
    resolve an actual leader (e.g. ``lens release check`` run from the
    parent directory) must check for that themselves.
    """
    if len(project_configs) <= 1:
        return

    leaders = sorted(slug for slug, cfg, _ in project_configs if cfg.app_leader)
    if len(leaders) > 1:
        raise LensException(
            "multiple projects set [release] app_leader = true: "
            f"{', '.join(leaders)} — exactly one project may be the release "
            "leader for a Fly app serving multiple projects"
        )

    non_leader_enabled = sorted(
        slug for slug, cfg, _ in project_configs if cfg.enabled and not cfg.app_leader
    )
    if non_leader_enabled:
        raise LensException(
            "[release] is enabled on non-leader project(s) "
            f"{', '.join(non_leader_enabled)} — only the release leader "
            "(app_leader = true) may enable release automation in a "
            "multi-project deployment; disable [release] there or make it "
            "the leader instead"
        )

    seen: dict[str, tuple[str, str, str]] = {}
    conflicts: list[str] = []
    for slug, _cfg, dataset_repos in project_configs:
        for repo in dataset_repos:
            prior = seen.get(repo.name)
            if prior is None:
                seen[repo.name] = (slug, repo.git_url, repo.ref)
            elif (prior[1], prior[2]) != (repo.git_url, repo.ref):
                conflicts.append(
                    f"dataset_repo '{repo.name}': '{prior[0]}' declares "
                    f"{prior[1]}@{prior[2]}, '{slug}' declares "
                    f"{repo.git_url}@{repo.ref}"
                )

    if conflicts:
        raise LensException(
            "conflicting [[dataset_repo]] declarations across projects "
            "sharing this Fly app: " + "; ".join(conflicts)
        )


def find_release_leader_slug(project_roots: dict[str, Path]) -> str | None:
    """Return the slug of the release leader among *project_roots*.

    Scans each project's ``lens.toml`` for ``[release] app_leader = true``.
    Returns ``None`` when there is at most one project — the lone project is
    trivially the leader, and the caller should use whatever slug was
    originally requested rather than requiring an explicit ``app_leader``
    marker.

    Raises :class:`LensException` when multiple projects match.
    """
    if len(project_roots) <= 1:
        return None

    leaders: list[str] = []
    for slug, root in project_roots.items():
        lens_toml = root / "lens.toml"
        if not lens_toml.exists():
            continue
        with lens_toml.open("rb") as f:
            raw: dict[str, Any] = tomllib.load(f)
        cfg = parse_release_config(raw)
        if cfg.app_leader:
            leaders.append(slug)

    if len(leaders) > 1:
        raise LensException(
            "multiple projects set [release] app_leader = true: "
            f"{', '.join(sorted(leaders))}"
        )
    if leaders:
        return leaders[0]
    return None
