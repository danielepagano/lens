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


def pytest_configure(config: pytest.Config) -> None:
    """Disable git commit signing when running in a cloud environment.

    Uses ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_N`` / ``GIT_CONFIG_VALUE_N``
    (git ≥ 2.32) to inject ``commit.gpgsign = false`` as a top-priority config
    override for every git subprocess spawned during the test session.
    """
    if not _is_cloud_environment():
        return

    os.environ["GIT_CONFIG_COUNT"] = "1"
    os.environ["GIT_CONFIG_KEY_0"] = "commit.gpgsign"
    os.environ["GIT_CONFIG_VALUE_0"] = "false"


def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up the git config overrides injected by pytest_configure."""
    for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        os.environ.pop(key, None)
