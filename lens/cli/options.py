"""Shared CLI option definitions for operators.

All help strings are imported from ``lens.cli.help_strings`` so they
are defined in one place and can be translated without touching CLI logic.
"""

from __future__ import annotations

from typing import Any

import typer

from lens.cli.help_strings import (
    OPT_INCLUDE,
    OPT_LLM,
    OPT_MENTION,
    OPT_PIN,
    OPT_REASONING,
    OPT_UNPIN,
)


def pin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--pin",
        "-p",
        help=help_override or OPT_PIN,
    )


def mention_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--mention",
        "-M",
        help=help_override or OPT_MENTION,
    )


def include_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--include",
        "-I",
        help=help_override or OPT_INCLUDE,
    )


def unpin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--unpin",
        "-u",
        help=help_override or OPT_UNPIN,
    )


def module_keys(values: list[str], prefix: str) -> list[str]:
    """Normalize repeated ``--module`` values into bare keys.

    Accepts either the key (``combat``) or the canonical id (``rules.combat``),
    because both read naturally on a command line and the operator only ever
    stores the key.  Blanks are dropped and duplicates collapse, so a repeated
    flag never turns into two copies of one module in the prompt.
    """
    keys: list[str] = []
    for raw in values:
        key = raw.strip()
        if key.startswith(prefix):
            key = key[len(prefix) :]
        if key and key not in keys:
            keys.append(key)
    return keys


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
