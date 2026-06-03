"""CLI adapter for media commands: generate, attach, and TTS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from lens.core.address import NarrativeAddress
from lens.core.commands.generate import generate as generate_core
from lens.core.commands.media_tts import iter_node_tts_playback
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, resolve_address

from .attach import attach_app

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Image generation, TTS, attachment, and related commands.",
)


@app.command(no_args_is_help=True)
def generate(
    prompt: str | None = typer.Argument(
        None,
        help="Prompt text. May contain @-mentions. Omit if using --from.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=(
            "[[image]] id from lens.toml (default: first block, shown as [default] "
            "when id is omitted)."
        ),
    ),
    aspect: str | None = typer.Option(
        None,
        "--aspect",
        "-a",
        help=(
            "Aspect ratio; must be one of the backend's aspect_ratios in lens.toml "
            "(default: first listed value, or sidecar when using --from)."
        ),
    ),
    size: str | None = typer.Option(
        None,
        "--size",
        "-s",
        help=(
            "Resolution tier; must be one of the backend's sizes in lens.toml "
            "(default: first listed value, or sidecar when using --from)."
        ),
    ),
    batch: int | None = typer.Option(
        None,
        "--batch",
        "-b",
        help=(
            "How many images (default: 1; capped by the backend's `max_batch`, "
            "or sidecar `batch_size` when using --from)."
        ),
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help=(
            "Folder name under generated/ (default: slug derived from the "
            "resolved prompt, or sidecar folder when using --from)."
        ),
    ),
    negative: str | None = typer.Option(
        None,
        "--negative",
        "-n",
        help="Optional negative prompt (default: none, or sidecar when using --from).",
    ),
    from_sidecar: Path | None = typer.Option(
        None,
        "--from",
        help=(
            "Batch sidecar YAML: mount-relative (e.g. generated/<slug>/b_1.yaml) "
            "or absolute path inside mount_point. Pre-fills prompt and flags; "
            "CLI args override."
        ),
        show_default=False,
    ),
    ref: list[str] = typer.Option(
        [],
        "--ref",
        help=(
            "Mount-relative reference image path if supported (repeatable). "
            "Requires s3:// mount_point."
        ),
    ),
) -> None:
    """Generate images via the configured backend and save them to the mount."""
    try:
        session = ProjectSession.from_cwd()
        result = generate_core(
            session,
            prompt,
            aspect=aspect,
            size=size,
            batch=batch,
            slug=slug,
            negative_prompt=negative,
            model_id=model,
            from_sidecar=from_sidecar,
            ref_paths=ref or None,
        )
    except LensException as e:
        typer.echo(f"lens media generate: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"saved batch {result.batch_seq} to generated/{result.slug}/ "
        f"(model={result.descriptor_id})"
    )
    for path in result.paths:
        typer.echo(f"  {path}")
    typer.echo(f"sidecar: {result.sidecar_path}")


@app.command(no_args_is_help=True)
def tts(
    address: str = typer.Argument(
        ...,
        help=(
            "Narrative node address (e.g. /@cursor, /chapter-1). "
            "Optional line slice @N or @N:M (physical lines in the node file)."
        ),
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=(
            "[[speech]] id from lens.toml (default: first block, shown as [default] "
            "when id is omitted)."
        ),
    ),
    voice: str | None = typer.Option(
        None,
        "--voice",
        "-v",
        help=(
            "Voice id (xAI: eve, ara, rex, sal, leo). "
            "Default: [[speech]] default_voice if set, else eve."
        ),
    ),
    language: str = typer.Option(
        "en",
        "--language",
        "-l",
        help="BCP-47 language code (e.g. en, auto).",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        help="Do not auto-play with ffplay after each chunk.",
    ),
) -> None:
    """Synthesize a narrative node line-by-line; MP3s live under ``tts-cache/`` on the mount."""
    try:
        session = ProjectSession.from_cwd()
        try:
            addr = NarrativeAddress.parse(address.strip())
        except ValueError as e:
            typer.echo(f"lens media tts: invalid address: {e}", err=True)
            raise typer.Exit(1)
        try:
            resolved = resolve_address(addr.node_only(), session.project_root)
        except ValueError as e:
            typer.echo(f"lens media tts: {e}", err=True)
            raise typer.Exit(1)
        target = resolved.to_node(session.project_root)
        if not target.exists():
            typer.echo(f"lens media tts: node does not exist: {address}", err=True)
            raise typer.Exit(1)

        for segment in iter_node_tts_playback(
            session,
            target,
            line_start_1=addr.line,
            line_end_1=addr.line_end,
            voice_id=voice,
            language=language,
            model_id=model,
        ):
            audio = b"".join(segment.chunks)
            label = "cached" if segment.from_cache else "saved"
            typer.echo(
                f"{label} {segment.mount_relative_path} "
                f"({len(audio):,} bytes, {segment.content_type})"
            )
            if not silent and shutil.which("ffplay") is not None:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-i", "-"],
                    input=audio,
                    check=False,
                )
    except LensException as e:
        typer.echo(f"lens media tts: {e}", err=True)
        raise typer.Exit(1)


app.add_typer(attach_app, name="attach")
