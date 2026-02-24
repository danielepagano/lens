"""Lens CLI entry point."""

from __future__ import annotations

import sys

import typer

from lens.commands import register_commands

app = typer.Typer(
    name="lens",
    help="Lens: narrative engine with fractal summarization",
    no_args_is_help=True,
)
register_commands(app)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
