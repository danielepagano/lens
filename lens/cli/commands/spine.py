"""CLI adapter for ``lens spine``."""

from __future__ import annotations

import json

import typer

from lens.cli.help_strings import (
    ARG_SPINE_ADDR,
    ARG_SPINE_LINE,
    CMD_SPINE,
    DESC_SPINE,
    HELP_OPTS,
    OPT_SPINE_CHARS_PER_TOKEN,
    OPT_SPINE_JSON,
    OPT_SPINE_OUTLINE,
    OPT_SPINE_TEXT,
    SPINE_EMPTY_NOTE,
)
from lens.core.commands.spine import (
    DEFAULT_CHARS_PER_TOKEN,
    ROLE_CURRENT,
    SpineNode,
    SpineReport,
    spine_report,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_SPINE,
    context_settings={"help_option_names": HELP_OPTS},
)

_RULE_WIDTH = 72
_OUTLINE_ADDR_WIDTH = 34
_OUTLINE_NUM_WIDTH = 9


# `--outline` deliberately has no short flag: `-o` is `--operator` on
# `lens explain`, and `lens spine -o play` would quietly mean "outline" and
# then fail on `play` as an address.
@app.callback(help=DESC_SPINE)
def spine(
    address: str | None = typer.Argument(None, help=ARG_SPINE_ADDR),
    line: int | None = typer.Argument(None, help=ARG_SPINE_LINE),
    outline: bool = typer.Option(False, "--outline", help=OPT_SPINE_OUTLINE),
    text_only: bool = typer.Option(False, "--text", "-t", help=OPT_SPINE_TEXT),
    as_json: bool = typer.Option(False, "--json", help=OPT_SPINE_JSON),
    chars_per_token: int = typer.Option(
        DEFAULT_CHARS_PER_TOKEN, "--chars-per-token", help=OPT_SPINE_CHARS_PER_TOKEN
    ),
) -> None:
    if outline and text_only:
        typer.echo("lens spine: --outline and --text are mutually exclusive", err=True)
        raise typer.Exit(1)
    try:
        session = ProjectSession.from_cwd()
        report = spine_report(
            session,
            address=address,
            line=line,
            chars_per_token=chars_per_token,
        )
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens spine: {e}", err=True)
        raise typer.Exit(1)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
        return
    if text_only:
        # Body only, so the spine can be piped somewhere without a header to
        # strip.  An empty spine prints nothing at all rather than a notice,
        # which would land in the pipe as if it were prose.
        body = report.text
        if body:
            typer.echo(body)
        return

    _print_header(report)
    if outline:
        _print_outline(report)
    else:
        _print_prose(report)


def _print_header(report: SpineReport) -> None:
    header = f"Spine at {report.address}"
    if report.line is not None:
        header += f" — as of line {report.line}"
    header += (
        f" — {len(report.contributing)} of {len(report.nodes)} node(s) with prose, "
        f"{report.total_bytes:,} bytes, ~{report.total_tokens:,} tokens"
    )
    typer.echo(header)

    if report.open_session is not None:
        typer.echo(
            f"Next generation here: {report.operator} "
            f"(inside an open {report.open_session} session; close it with --end)"
        )
    elif report.operator is not None:
        typer.echo(f"Next generation here: {report.operator}")


def _node_label(node: SpineNode, *, short: bool = False) -> str:
    """The node's name plus whatever a reader needs to know about it.

    *short* names only the node's own key, for the outline, where indentation
    already carries the lineage and a full address would be truncated away on
    a deep spine.
    """
    label = node.address.rsplit("/", 1)[-1] if short else node.address
    marks: list[str] = []
    if node.role == ROLE_CURRENT:
        marks.append("cursor")
    if node.truncated:
        marks.append("truncated")
    if not node.has_file:
        marks.append("no file")
    elif not node.contributes:
        marks.append("empty")
    return f"{label} ({', '.join(marks)})" if marks else label


def _opening(node: SpineNode) -> str:
    """The node's first non-blank line, which is what a reader scans for."""
    for raw in node.text.split("\n"):
        stripped = raw.strip()
        if stripped:
            return stripped
    return ""


def _print_outline(report: SpineReport) -> None:
    typer.echo("")
    typer.echo(
        f"{'NODE':<{_OUTLINE_ADDR_WIDTH}}"
        f"{'tokens':>{_OUTLINE_NUM_WIDTH}}"
        f"{'bytes':>{_OUTLINE_NUM_WIDTH}}"
        f"{'lines':>{_OUTLINE_NUM_WIDTH}}"
        "  opens with"
    )
    has_empty = False
    for node in report.nodes:
        has_empty = has_empty or not node.contributes
        indent = "  " * node.depth
        label = (indent + _node_label(node, short=True))[:_OUTLINE_ADDR_WIDTH]
        opening = _opening(node)
        typer.echo(
            f"{label:<{_OUTLINE_ADDR_WIDTH}}"
            f"{node.tokens:>{_OUTLINE_NUM_WIDTH},}"
            f"{node.bytes:>{_OUTLINE_NUM_WIDTH},}"
            f"{node.lines:>{_OUTLINE_NUM_WIDTH},}"
            f"  {opening[:60]}"
        )
    if has_empty:
        typer.echo("")
        typer.echo(SPINE_EMPTY_NOTE)


def _print_prose(report: SpineReport) -> None:
    for node in report.nodes:
        typer.echo("")
        typer.echo(_rule(node))
        if node.contributes:
            typer.echo(node.text)
    if not report.contributing:
        typer.echo("")
        typer.echo("The spine is empty: no node from the root to the cursor has prose.")


def _rule(node: SpineNode) -> str:
    """A labelled separator, so a long spine stays navigable when scrolled."""
    size = "" if not node.contributes else f" · {node.bytes:,} bytes"
    label = f"── {_node_label(node)} · {node.role}{size} "
    pad = max(_RULE_WIDTH - len(label), 3)
    return label + "─" * pad
