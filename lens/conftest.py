"""Pytest session configuration for the Lens test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _is_cloud_environment() -> bool:
    """Detect a Claude Code cloud session.

    Cloud sessions enforce signed commits globally via a hook that calls an
    external API (``/tmp/code-sign``).  Tests that create temporary git
    repositories and run ``git commit`` in them will fail unless signing is
    disabled for the test session.

    The presence of the signing key file is the most stable indicator.
    """
    return Path("/home/claude/.ssh/commit_signing_key.pub").exists()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Reload self-registering catalog modules after tests that clear the registry."""
    del item
    from lens.core.modalities.bootstrap import ensure_modalities_registered

    ensure_modalities_registered()


def _git_test_config_entries() -> list[tuple[str, str]]:
    """Config overrides for git subprocesses spawned during pytest."""
    entries = [
        ("user.email", "test@test.com"),
        ("user.name", "Lens Test"),
    ]
    if _is_cloud_environment():
        entries.append(("commit.gpgsign", "false"))
    return entries


def pytest_configure(config: pytest.Config) -> None:
    """Inject git config for every subprocess in the test session.

    GitHub Actions and similar CI images have no ``user.name`` / ``user.email``,
    so bare clones cannot commit. Cloud sessions also need signing disabled.
    """
    del config
    entries = _git_test_config_entries()
    os.environ["GIT_CONFIG_COUNT"] = str(len(entries))
    for i, (key, value) in enumerate(entries):
        os.environ[f"GIT_CONFIG_KEY_{i}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{i}"] = value


def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up the git config overrides injected by pytest_configure."""
    del config
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    for i in range(count):
        os.environ.pop(f"GIT_CONFIG_KEY_{i}", None)
        os.environ.pop(f"GIT_CONFIG_VALUE_{i}", None)
    os.environ.pop("GIT_CONFIG_COUNT", None)
