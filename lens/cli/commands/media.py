"""CLI adapter for media commands: generate, attach, move, and TTS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_TTS_ADDR,
    ARG_PROMPT_OPT as ARG_MEDIA_PROMPT,
    CMD_MEDIA,
    HELP_OPTS,
    MEDIA_MODEL,
    MEDIA_ASPECT,
    MEDIA_SIZE,
    MEDIA_BATCH,
    MEDIA_SLUG,
    MEDIA_NEGATIVE,
    MEDIA_FROM,
    MEDIA_REF,
    TTS_MODEL,
    TTS_VOICE,
    TTS_LANG,
    TTS_SILENT,
)
from lens.core.address import NarrativeAddress
from lens.core.commands.attach import update_media_references
from lens.core.commands.generate import generate as generate_core
from lens.core.commands.media_tts import iter_node_tts_playback
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, get_mount_backend, resolve_address

from .attach import attach_app

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=CMD_MEDIA,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.command(no_args_is_help=True)
def generate(
    prompt: str | None = typer.Argument(
        None,
        help=ARG_MEDIA_PROMPT,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=MEDIA_MODEL,
    ),
    aspect: str | None = typer.Option(
        None,
        "--aspect",
        "-a",
        help=MEDIA_ASPECT,
    ),
    size: str | None = typer.Option(
        None,
        "--size",
        "-s",
        help=MEDIA_SIZE,
    ),
    batch: int | None = typer.Option(
        None,
        "--batch",
        "-b",
        help=MEDIA_BATCH,
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help=MEDIA_SLUG,
    ),
    negative: str | None = typer.Option(
        None,
        "--negative",
        "-n",
        help=MEDIA_NEGATIVE,
    ),
    from_sidecar: Path | None = typer.Option(
        None,
        "--from",
        help=MEDIA_FROM,
        show_default=False,
    ),
    ref: list[str] = typer.Option(
        [],
        "--ref",
        help=MEDIA_REF,
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
        help=ARG_TTS_ADDR,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=TTS_MODEL,
    ),
    voice: str | None = typer.Option(
        None,
        "--voice",
        "-v",
        help=TTS_VOICE,
    ),
    language: str = typer.Option(
        "en",
        "--language",
        "-l",
        help=TTS_LANG,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        help=TTS_SILENT,
    ),
) -> None:
    """Synthesize a narrative node line-by-line; MP3s live under tts-cache/ on the mount."""
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


@app.command(no_args_is_help=True)
def move(
    source: str = typer.Argument(
        ...,
        help="Current mount-relative path of the file to move.",
    ),
    destination: str = typer.Argument(
        ...,
        help="New mount-relative path (same directory = rename).",
    ),
) -> None:
    """Move or rename a media file and update its embed references in narrative/knowledge."""
    try:
        session = ProjectSession.from_cwd()
        backend = get_mount_backend(session.project_root)
        if backend is None:
            raise LensException("no mount_point configured in lens.toml")
        new_path = backend.move(source, destination)
        refs_updated = update_media_references(session.project_root, source, destination)
        typer.echo(f"moved: {source} -> {new_path}")
        if refs_updated:
            typer.echo(f"updated {refs_updated} file(s) with new references")
    except LensException as e:
        typer.echo(f"lens media move: {e}", err=True)
        raise typer.Exit(1)
    except FileNotFoundError:
        typer.echo(f"lens media move: not found: {source}", err=True)
        raise typer.Exit(1)
    except FileExistsError as e:
        typer.echo(f"lens media move: {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"lens media move: {e}", err=True)
        raise typer.Exit(1)


app.add_typer(attach_app, name="attach")
