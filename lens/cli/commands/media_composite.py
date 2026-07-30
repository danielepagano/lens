"""CLI adapter for media-composite commands: chromakey background removal."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_CHROMAKEY_PATH,
    CMD_MEDIA_COMPOSITE,
    HELP_OPTS,
    MEDIA_COMPOSITE_CHROMAKEY,
    MEDIA_COMPOSITE_CORE_TOL,
    MEDIA_COMPOSITE_DILATE_PX,
    MEDIA_COMPOSITE_KEY,
    MEDIA_COMPOSITE_OUT,
    MEDIA_COMPOSITE_PREVIEW,
    MEDIA_COMPOSITE_RESIDUAL_THRESH,
)
from lens.core.commands.media_composite import chromakey as chromakey_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

# Registered as the top-level "media-composite" command via this override (see
# lens/cli/commands/__init__.py's _discover_commands); gated behind having a
# mount configured, same as "media".
cli_name = "media-composite"

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=CMD_MEDIA_COMPOSITE,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.command(no_args_is_help=True, help=MEDIA_COMPOSITE_CHROMAKEY)
def chromakey(
    path: str = typer.Argument(..., help=ARG_CHROMAKEY_PATH),
    key: str | None = typer.Option(
        None,
        "--key",
        "-k",
        help=MEDIA_COMPOSITE_KEY,
    ),
    core_tol: float | None = typer.Option(
        None,
        "--core-tol",
        help=MEDIA_COMPOSITE_CORE_TOL,
    ),
    residual_thresh: float = typer.Option(
        10.0,
        "--residual-thresh",
        help=MEDIA_COMPOSITE_RESIDUAL_THRESH,
    ),
    dilate_px: int | None = typer.Option(
        None,
        "--dilate-px",
        help=MEDIA_COMPOSITE_DILATE_PX,
    ),
    preview: Path | None = typer.Option(
        None,
        "--preview",
        help=MEDIA_COMPOSITE_PREVIEW,
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help=MEDIA_COMPOSITE_OUT,
    ),
) -> None:
    """Remove a chroma-keyed background; preview locally or save to the mount."""
    try:
        session = ProjectSession.from_cwd()
        result = chromakey_core(
            session,
            path,
            key=key,
            core_tol=core_tol,
            residual_thresh=residual_thresh,
            dilate_px=dilate_px,
            preview_path=preview,
            out_path=out,
        )
    except LensException as e:
        typer.echo(f"lens media-composite chromakey: {e}", err=True)
        raise typer.Exit(1)

    if result.saved:
        typer.echo(f"saved {result.output_path} (composite: foreground)")
    else:
        typer.echo(f"preview written to {result.output_path}")
    typer.echo(
        f"  key={result.key_hex} core_tol={result.core_tol:.1f} "
        f"residual_thresh={result.residual_thresh} dilate_px={result.dilate_px} "
        f"({result.n_corners_used}/4 corners)"
    )
