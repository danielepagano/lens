"""Release system configuration parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

from lens.core.git_ssh_remote import parse_git_ssh_remote

_VALID_AUTO_UPDATE = frozenset({"off", "minor", "major"})


@dataclass(frozen=True)
class ReleaseConfig:
    enabled: bool = False
    lens_repo_url: str = ""
    auto_update: str = "off"
    requested_version: str = ""
    data_major_version: int = 1
    migration_pending: bool = False
    migration_target_version: str = ""
    migration_commit: str = ""


@dataclass(frozen=True)
class DatasetRepoConfig:
    name: str
    git_url: str
    ref: str = "main"


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
        "auto_update",
        "requested_version",
        "migration_pending",
        "migration_target_version",
        "migration_commit",
    ):
        val = raw_dict.get(field_name)
        if val is not None:
            kwargs[field_name] = val
    dmv = raw_dict.get("data_major_version")
    if dmv is not None:
        kwargs["data_major_version"] = dmv
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

    if config.auto_update not in _VALID_AUTO_UPDATE:
        lines.append(
            (
                "error",
                "release auto_update",
                f"must be one of {', '.join(sorted(_VALID_AUTO_UPDATE))}, got {config.auto_update!r}",
            )
        )

    if config.data_major_version < 0:
        lines.append(
            (
                "error",
                "release data_major_version",
                f"must be a non-negative integer, got {config.data_major_version!r}",
            )
        )

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
