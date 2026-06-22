"""Shared CLI option definitions for operators.

All help strings are imported from ``lens.cli.help_strings`` so they
are defined in one place and can be translated without touching CLI logic.
"""

from __future__ import annotations

from typing import Any

import typer

from lens.cli.help_strings import OPT_LLM, OPT_PIN, OPT_REASONING, OPT_UNPIN


def pin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--pin",
        "-p",
        help=help_override or OPT_PIN,
    )


def unpin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--unpin",
        "-u",
        help=help_override or OPT_UNPIN,
    )


def llm_option(*, summary: bool = False) -> Any:
    return typer.Option(
        None,
        "--llm",
        "-l",
        help=OPT_LLM,
    )


def reasoning_option() -> Any:
    return typer.Option(
        None,
        "--reasoning",
        help=OPT_REASONING,
    )
