"""Release status: combine config, live tag data, and installed version."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lens.core.release.config import (
    DatasetRepoConfig,
    parse_dataset_repo_configs,
    parse_release_config,
    ReleaseConfig,
)
from lens.core.release.version import (
    compute_local_version,
    find_lens_repo_root,
    installed_version,
    latest_overall,
    list_remote_tags,
    parse_semver_tag,
    SemverTag,
)


@dataclass
class ReleaseStatus:
    enabled: bool = False

    lens_repo_url: str = ""
    requested_version: str = ""
    requested_from_commit: str = ""
    app_leader: bool = False
    dataset_repos: list[DatasetRepoConfig] = field(default_factory=list[DatasetRepoConfig])

    installed_version_str: str | None = None
    installed_semver: SemverTag | None = None
    local_checkout_version: str | None = None
    latest_available: SemverTag | None = None
    latest_available_str: str | None = None
    update_available: bool = False
    available_tags: list[SemverTag] = field(default_factory=list[SemverTag])
    tag_count: int = 0

    remote_error: str = ""


def compute_release_status(project_root: Path) -> ReleaseStatus:
    """Compute the full release status combining config + live checks.

    This is the single entry point consumed by both the CLI ``stats``
    command and ``GET /{slug}/stats``.  Network failures are non-fatal
    — ``remote_error`` carries the message, but other fields are populated.
    """
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return ReleaseStatus()

    import tomllib

    with lens_toml.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)

    cfg: ReleaseConfig = parse_release_config(raw)
    dataset_repos: list[DatasetRepoConfig] = parse_dataset_repo_configs(raw)

    if not cfg.enabled:
        return ReleaseStatus()

    status = ReleaseStatus(
        enabled=True,
        lens_repo_url=cfg.lens_repo_url,
        requested_version=cfg.requested_version,
        requested_from_commit=cfg.requested_from_commit,
        app_leader=cfg.app_leader,
        dataset_repos=dataset_repos,
    )

    # "Installed" reflects the deployed container's baked-in LENS_VERSION env
    # var only — None when unset (a desktop checkout, or a container that
    # wasn't built with the ARG set).
    # It must NOT fall back to compute_local_version(): conflating the two
    # would silently mask a real deployment misconfiguration (missing/unset
    # LENS_VERSION) behind a plausible-looking but unrelated version string.
    inst_str = installed_version()
    status.installed_version_str = inst_str
    if inst_str:
        status.installed_semver = parse_semver_tag(inst_str)

    # Separately, and only when there's an actual local Lens repo checkout
    # to compute from (desktop dev, not a deployed container), surface what
    # `lens deploy push` would bake LENS_VERSION to right now (decision #7).
    # This is informational/local-sanity-check data, distinct from
    # "installed" — a pending build target, not a deployed fact.
    # Only computed when LENS_VERSION is unset (we're on a desktop, not in
    # a deployed container) to avoid side effects like auto-fetching tags.
    if status.installed_version_str is None and find_lens_repo_root() is not None:
        status.local_checkout_version = compute_local_version()

    if cfg.lens_repo_url:
        try:
            tags = list_remote_tags(cfg.lens_repo_url)
            status.available_tags = tags
            status.tag_count = len(tags)
            latest = latest_overall(tags)
            status.latest_available = latest
            if latest is not None:
                status.latest_available_str = latest.tag
            if latest is not None and status.installed_semver is not None:
                status.update_available = latest > status.installed_semver
        except Exception as exc:
            status.remote_error = str(exc)

    return status


def compute_latest_available(project_root: Path) -> str | None:
    """Compute the latest available version tag from the remote repo.

    Lightweight helper used by ``GET /release/latest`` and transaction
    endpoints — does not need most of the fields that
    :func:`compute_release_status` builds.  Returns ``None`` when release
    is disabled, no remote URL is configured, or the network call fails.
    """
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None

    import tomllib

    with lens_toml.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)

    cfg = parse_release_config(raw)
    if not cfg.enabled or not cfg.lens_repo_url:
        return None

    try:
        tags = list_remote_tags(cfg.lens_repo_url)
        latest = latest_overall(tags)
        return latest.tag if latest is not None else None
    except Exception:
        return None
