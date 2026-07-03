"""Unit tests asserting the deploy Dockerfile contains expected ARG/ENV lines."""

from __future__ import annotations

from pathlib import Path

_DOCKERFILE = Path(__file__).resolve().parent.parent.parent.parent / "deploy" / "Dockerfile"


def test_dockerfile_contains_lens_version_arg() -> None:
    content = _DOCKERFILE.read_text()
    assert "ARG LENS_VERSION=dev" in content


def test_dockerfile_contains_lens_version_env() -> None:
    content = _DOCKERFILE.read_text()
    assert "ENV LENS_VERSION=${LENS_VERSION}" in content
