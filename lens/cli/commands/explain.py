"""CLI adapter for ``lens explain``."""

from __future__ import annotations

import json

import typer

from lens.cli.help_strings import (
    ARG_EXPLAIN_ADDR,
    ARG_EXPLAIN_LINE,
    CMD_EXPLAIN,
    DESC_EXPLAIN,
    EXPLAIN_CACHE_NOTE,
    HELP_OPTS,
    OPT_EXPLAIN_CHARS_PER_TOKEN,
    OPT_EXPLAIN_JSON,
    OPT_EXPLAIN_OPERATOR,
    OPT_EXPLAIN_PROMPT,
    OPT_EXPLAIN_SORT,
    OPT_EXPLAIN_VERBOSE,
)
from lens.core.commands.explain import (
    DEFAULT_CHARS_PER_TOKEN,
    SORT_ORDER,
    ExplainReport,
    explain_context,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_EXPLAIN,
    context_settings={"help_option_names": HELP_OPTS},
)

_NAME_WIDTH = 44
_NUM_WIDTH = 8
_PCT_WIDTH = 7


@app.callback(help=DESC_EXPLAIN)
def explain(
    address: str | None = typer.Argument(None, help=ARG_EXPLAIN_ADDR),
    line: int | None = typer.Argument(None, help=ARG_EXPLAIN_LINE),
    operator: str | None = typer.Option(
        None, "--operator", "-o", help=OPT_EXPLAIN_OPERATOR
    ),
    prompt: str | None = typer.Option(None, "--prompt", "-p", help=OPT_EXPLAIN_PROMPT),
    sort: str = typer.Option(SORT_ORDER, "--sort", "-s", help=OPT_EXPLAIN_SORT),
    as_json: bool = typer.Option(False, "--json", help=OPT_EXPLAIN_JSON),
    verbose: bool = typer.Option(False, "--verbose", "-v", help=OPT_EXPLAIN_VERBOSE),
    chars_per_token: int = typer.Option(
        DEFAULT_CHARS_PER_TOKEN,
        "--chars-per-token",
        help=OPT_EXPLAIN_CHARS_PER_TOKEN,
    ),
) -> None:
    try:
        session = ProjectSession.from_cwd()
        report = explain_context(
            session,
            address=address,
            line=line,
            operator=operator,
            prompt=prompt,
            sort=sort,
            chars_per_token=chars_per_token,
        )
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens explain: {e}", err=True)
        raise typer.Exit(1)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
        return

    _print_table(report, verbose=verbose)


def _percent(size: int, total: int) -> float:
    return (size / total * 100.0) if total else 0.0


def _row(name: str, tokens: int, size: int, percent: float, trailer: str) -> str:
    return (
        f"{name[:_NAME_WIDTH]:<{_NAME_WIDTH}}"
        f"{tokens:>{_NUM_WIDTH},}"
        f"{size:>{_NUM_WIDTH},}"
        f"{percent:>{_PCT_WIDTH}.1f}%"
        f"  {trailer}"
    )


def _print_table(report: ExplainReport, *, verbose: bool) -> None:
    header = f"Context at {report.address} — operator: {report.operator}"
    if report.line is not None:
        header += f" — as of line {report.line}"
    typer.echo(header)
    if report.active_modalities:
        typer.echo(f"Modalities: {', '.join(report.active_modalities)}")
    typer.echo("")
    typer.echo(
        f"{'BLOCK / component':<{_NAME_WIDTH}}"
        f"{'tokens':>{_NUM_WIDTH}}"
        f"{'bytes':>{_NUM_WIDTH}}"
        f"{'share':>{_PCT_WIDTH + 1}}"
        f"  why"
    )

    for block in report.blocks:
        typer.echo(
            _row(block.label, block.tokens, block.bytes, block.percent, block.cache)
        )
        for component in block.components:
            typer.echo(
                _row(
                    "  " + component.id,
                    component.tokens,
                    component.bytes,
                    component.percent,
                    component.provenance,
                )
            )
        # Framing is real cost but it is the same handful of bytes on every
        # run, so it only earns a row when the reader asked to see the
        # columns reconcile.
        if verbose and block.framing_bytes:
            typer.echo(
                _row(
                    "  (block framing)",
                    block.framing_tokens,
                    block.framing_bytes,
                    _percent(block.framing_bytes, report.total_bytes),
                    "block header/footer and separators",
                )
            )

    if verbose and report.other_bytes:
        typer.echo(
            _row(
                "(message separators)",
                report.other_tokens,
                report.other_bytes,
                _percent(report.other_bytes, report.total_bytes),
                "",
            )
        )

    typer.echo("")
    typer.echo(
        _row(
            "TOTAL",
            report.total_tokens,
            report.total_bytes,
            100.0,
            f"{report.message_count} message(s), ~{report.chars_per_token} chars/token",
        )
    )

    if verbose and report.excluded:
        typer.echo("")
        typer.echo("Not sent to the model:")
        for component in report.excluded:
            typer.echo(f"  {component.id}: {component.provenance}")

    if verbose:
        typer.echo("")
        typer.echo(EXPLAIN_CACHE_NOTE)

    for warning in report.warnings:
        typer.echo(f"warning: {warning}", err=True)
