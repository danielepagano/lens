"""Semver tag parsing, remote tag listing, and installed-version checks
for the Lens release system."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True)
class SemverTag:
    major: int
    minor: int
    patch: int

    @property
    def tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_str(cls, s: str) -> SemverTag:
        m = _SEMVER_RE.match(s.strip())
        if m is None:
            raise ValueError(f"not a valid semver tag: {s!r}")
        return cls(major=int(m.group(1)), minor=int(m.group(2)), patch=int(m.group(3)))


def parse_semver_tag(ref: str) -> SemverTag | None:
    """Parse a ``vMAJOR.MINOR.PATCH`` tag string into a ``SemverTag``.

    Returns ``None`` for tags that don't match (prereleases, non-semver, etc.).
    """
    m = _SEMVER_RE.match(ref.strip())
    if m is None:
        return None
    return SemverTag(
        major=int(m.group(1)),
        minor=int(m.group(2)),
        patch=int(m.group(3)),
    )


def list_remote_tags(
    git_url: str,
    *,
    ssh_key_path: str | None = None,
) -> list[SemverTag]:
    """Fetch and parse semver tags from a remote git repository.

    Runs ``git ls-remote --tags <url>`` and filters to valid
    ``vMAJOR.MINOR.PATCH`` tags.  Non-zero exit (network failure, bad URL)
    returns an empty list — callers should treat this as non-fatal.

    Args:
        git_url: Remote git repository URL (SSH or HTTPS).
        ssh_key_path: Optional path to an SSH key for private repos.

    Returns:
        Sorted list of ``SemverTag`` objects (ascending).
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if ssh_key_path:
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_path}"

    r = subprocess.run(
        ["git", "ls-remote", "--tags", git_url],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return []

    tags: list[SemverTag] = []
    seen: set[tuple[int, int, int]] = set()
    for line in r.stdout.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.endswith("^{}"):
            continue
        tag_name = ref.removeprefix("refs/tags/")
        semver = parse_semver_tag(tag_name)
        if semver is not None:
            key = (semver.major, semver.minor, semver.patch)
            if key not in seen:
                seen.add(key)
                tags.append(semver)

    tags.sort()
    return tags


def latest_overall(tags: list[SemverTag]) -> SemverTag | None:
    """Return the latest (highest) semver tag, or ``None`` if empty."""
    return max(tags) if tags else None


def latest_within_major(tags: list[SemverTag], major: int) -> SemverTag | None:
    """Return the latest semver tag within a given major version, or ``None``."""
    candidates = [t for t in tags if t.major == major]
    return latest_overall(candidates)


def resolve_remote_ref_sha(git_url: str, ref: str = "HEAD") -> str | None:
    """Resolve a git ref to a commit SHA via ``git ls-remote``.

    Lightweight network call — no clone required. Returns ``None`` on
    failure (network error, missing ref, bad URL).
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", "ls-remote", git_url, ref],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split(maxsplit=1)[0]


def installed_version() -> str | None:
    """Return the currently installed Lens version from ``LENS_VERSION``.

    Returns ``None`` when running from a desktop checkout (env var not set).
    """
    return os.environ.get("LENS_VERSION")


def find_lens_repo_root() -> Path | None:
    """Find the Lens tool repository root by walking up from the ``lens`` package.

    Returns ``None`` when the package can't be located or is not in a git repo
    (e.g. installed from PyPI as a wheel, or running from a baked container
    image with no ``.git`` directory). Callers can use this to tell "no local
    checkout to compute a version from" apart from "checkout has no tags".
    """
    try:
        import lens as lens_pkg
    except ImportError:
        return None
    pkg_path = Path(lens_pkg.__file__).parent
    for parent in (pkg_path, *pkg_path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def list_local_tags(repo_root: Path) -> list[SemverTag]:
    """List semver tags from a local git repository."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", "tag"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return []
    tags: list[SemverTag] = []
    seen: set[tuple[int, int, int]] = set()
    for line in r.stdout.splitlines():
        semver = parse_semver_tag(line.strip())
        if semver is not None:
            key = (semver.major, semver.minor, semver.patch)
            if key not in seen:
                seen.add(key)
                tags.append(semver)
    tags.sort()
    return tags


def _fetch_tags_quiet(repo_root: Path) -> None:
    """Fetch tags from origin to populate local tag cache.

    Silently ignores failures (no remote, no network).
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return
    subprocess.run(
        ["git", "fetch", "origin", "--tags", "--quiet", "--force"],
        cwd=repo_root,
        capture_output=True,
        env=env,
    )


def compute_local_version(repo_root: Path | None = None) -> str:
    """Compute ``LENS_VERSION`` from the local Lens repo checkout.

    Follows Design Decision #7 in ``docs/release-system.md``:

    * HEAD matches the latest release tag → ``<tag>`` (e.g. ``v1.4.2``).
    * HEAD is ahead of the latest tag → ``<tag>+<short-hash>``.
    * No tags in the checkout → ``0.0.0+<short-hash>``.
    * Can't locate the Lens repo → ``0.0.0+unknown``.

    An explicit *repo_root* may be passed for testing; when ``None`` the
    function auto-detects the Lens repo via ``find_lens_repo_root()``.
    """
    root = repo_root or find_lens_repo_root()
    if root is None:
        return "0.0.0+unknown"

    _fetch_tags_quiet(root)
    tags = list_local_tags(root)

    short_hash = _git_rev_parse_short(root)

    if not tags:
        return f"0.0.0+{short_hash}"

    latest = latest_overall(tags)
    assert latest is not None  # tags is non-empty, so latest is always set

    if _head_is_at_tag(root, latest):
        return latest.tag

    return f"{latest.tag}+{short_hash}"


def _git_rev_parse_short(repo_root: Path) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _head_is_at_tag(repo_root: Path, target: SemverTag) -> bool:
    """Return ``True`` if HEAD points to a tag matching the given semver.

    Tags at HEAD are compared by parsed semver value, not literal string,
    since a repo's actual tag names may or may not carry the ``v`` prefix
    (e.g. a tag named ``0.1.0`` still matches ``SemverTag(0, 1, 0)``, whose
    normalized ``.tag`` property is ``v0.1.0``).
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return False
    tags_at_head = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    return any(parse_semver_tag(t) == target for t in tags_at_head)



