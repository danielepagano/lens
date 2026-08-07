"""CLI adapter for media compositing tools: chromakey background removal.

Nested under ``lens media`` as ``lens media composite`` (see
``lens/cli/commands/media.py``), inheriting the same mount-configured gate.
"""

from __future__ import annotations

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
    MEDIA_COMPOSITE_RESIDUAL_THRESH,
)
from lens.core.commands.media_composite import chromakey as chromakey_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

composite_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=CMD_MEDIA_COMPOSITE,
    context_settings={"help_option_names": HELP_OPTS},
)


@composite_app.command(no_args_is_help=True, help=MEDIA_COMPOSITE_CHROMAKEY)
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
    out: str | None = typer.Option(
        None,
        "--out",
        help=MEDIA_COMPOSITE_OUT,
    ),
) -> None:
    """Remove a chroma-keyed background and save a foreground PNG to the mount.

    Re-running on the same output path (default or ``--out``) overwrites it,
    so the usual flow is: run, look at the saved file, override ``--core-tol``
    (and re-run) if the cut isn't clean.
    """
    try:
        session = ProjectSession.from_cwd()
        result = chromakey_core(
            session,
            path,
            key=key,
            core_tol=core_tol,
            residual_thresh=residual_thresh,
            dilate_px=dilate_px,
            out_path=out,
        )
    except LensException as e:
        typer.echo(f"lens media composite chromakey: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"saved {result.output_path} (composite: foreground)")
    typer.echo(
        f"  key={result.key_hex} core_tol={result.core_tol:.1f} "
        f"residual_thresh={result.residual_thresh} dilate_px={result.dilate_px} "
        f"({result.n_corners_used}/4 corners)"
    )
    if result.n_frames > 1:
        typer.echo(
            f"  animated: {result.n_frames} frames, "
            f"{result.palette_colors}-colour palette with 8-bit alpha"
        )
    typer.echo(
        "  not clean? re-run with --core-tol (and optionally --key/--dilate-px/"
        "--residual-thresh) to override -- it overwrites this output."
    )
