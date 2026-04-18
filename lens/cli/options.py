"""Shared CLI option definitions for operators."""

from __future__ import annotations

from typing import Any

import typer


def pin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--pin",
        "-p",
        help=help_override or "KB ID to pin for this operator (repeatable)",
    )


def unpin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--unpin",
        "-u",
        help=help_override or "KB ID to unpin for this operator (repeatable)",
    )


def reasoning_option(help_override: str | None = None) -> Any:
    return typer.Option(
        None,
        "--reasoning",
        help=help_override or "Reasoning override: none, low, medium, high",
    )
