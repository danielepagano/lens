"""Node TTS: chunking, cache on the media mount, synthesis — yields playable byte streams."""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from lens.core.exceptions import LensException
from lens.core.mount import MountBackend
from lens.core.narrative import NarrativeNode
from lens.core.pinning import set_tts_cached_rev
from lens.core.project import ProjectSession, get_mount_backend
from lens.core.speech.chunks import (
    TTS_CHUNK_REVISION,
    TtsChunk,
    chunks_for_node,
    tts_cache_mount_prefix,
)
from lens.core.speech.synthesize_file import synthesize_speech_bytes
from lens.core.speech.tts_cache_sync import node_uses_tts_cache


@dataclass(frozen=True, slots=True)
class TtsPlaybackSegment:
    """One playable MP3: MIME type, mount-relative path (for logs), cache flag, byte stream."""

    content_type: str
    mount_relative_path: str
    from_cache: bool
    chunks: Iterable[bytes]


def read_mount_audio_bytes(backend: MountBackend, rel_file: str) -> tuple[bytes, str]:
    streamed = backend.stream_file(rel_file)
    if streamed is None:
        raise LensException(f"TTS cache missing at mount path {rel_file!r}")
    gen, ctype = streamed
    return (b"".join(gen), ctype)


def find_tts_chunk(node: NarrativeNode, *, line: int, chunk_id: str) -> TtsChunk:
    by_id: TtsChunk | None = None
    for ch in chunks_for_node(node):
        if ch.id == chunk_id:
            by_id = ch
        if ch.source_kept_line_1 == line and ch.id == chunk_id:
            return ch
    if by_id is not None:
        return by_id
    raise LensException(f"no TTS chunk for line {line} with id {chunk_id!r}")


def synthesize_or_load_chunk_mp3(
    session: ProjectSession,
    node: NarrativeNode,
    *,
    line: int,
    chunk_id: str,
    voice_id: str | None = None,
    language: str = "en",
    model_id: str | None = None,
) -> tuple[bytes, str, bool]:
    """Return ``(audio_bytes, content_type, from_cache)`` for one validated TTS chunk.

    Ensures ``tts_cached`` front matter is set (via :class:`~lens.core.storage.Storage`)
    before any mount cache read or write when it was not already set.
    """
    chosen = find_tts_chunk(node, line=line, chunk_id=chunk_id)

    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException(
            "TTS requires [project] mount_point in lens.toml (same as other lens media)"
        )

    storage = session.new_storage(owner=None)
    if not node_uses_tts_cache(node):
        set_tts_cached_rev(node, TTS_CHUNK_REVISION, storage)

    prefix = tts_cache_mount_prefix(node)
    filename = f"{chosen.id}.mp3"
    rel_file = f"{prefix}/{filename}"
    pr = session.project_root

    if backend.file_exists(rel_file):
        data, ctype = read_mount_audio_bytes(backend, rel_file)
        return (data, ctype, True)

    audio = synthesize_speech_bytes(
        pr,
        chosen.speak_text,
        voice_id=voice_id,
        language=language,
        model_id=model_id,
    )
    try:
        backend.put_file(prefix, filename, io.BytesIO(audio))
    except FileExistsError:
        data, ctype = read_mount_audio_bytes(backend, rel_file)
        return (data, ctype, True)
    return (audio, "audio/mpeg", False)


def iter_node_tts_playback(
    session: ProjectSession,
    node: NarrativeNode,
    *,
    line_start_1: int | None = None,
    line_end_1: int | None = None,
    voice_id: str | None = None,
    language: str = "en",
    model_id: str | None = None,
) -> Iterator[TtsPlaybackSegment]:
    """Yield each line chunk as a byte stream (mount cache read or synthesize + write).

    Optional *line_start_1* / *line_end_1* select physical lines in the node file
    (``@N`` / ``@N:M`` address syntax); annotation-only or empty slices yield nothing.

    Callers consume ``chunks`` once — pipe into ``ffplay -nodisp -autoexit -i -``
    (stdin), or ``bytes.join`` first. Cache lookup and ``put_file`` stay inside this iterator.
    """
    chunks = chunks_for_node(
        node,
        line_start_1=line_start_1,
        line_end_1=line_end_1,
    )
    if not chunks:
        return

    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException(
            "TTS requires [project] mount_point in lens.toml (same as other lens media)"
        )

    storage = session.new_storage(owner=None)
    set_tts_cached_rev(node, TTS_CHUNK_REVISION, storage)

    prefix = tts_cache_mount_prefix(node)
    pr = session.project_root

    for ch in chunks:
        filename = f"{ch.id}.mp3"
        rel_file = f"{prefix}/{filename}"
        if backend.file_exists(rel_file):
            streamed = backend.stream_file(rel_file)
            if streamed is None:
                raise LensException(f"TTS cache missing at mount path {rel_file!r}")
            gen, ctype = streamed
            yield TtsPlaybackSegment(
                content_type=ctype,
                mount_relative_path=rel_file,
                from_cache=True,
                chunks=gen,
            )
            continue

        audio = synthesize_speech_bytes(
            pr,
            ch.speak_text,
            voice_id=voice_id,
            language=language,
            model_id=model_id,
        )
        backend.put_file(prefix, filename, io.BytesIO(audio))
        yield TtsPlaybackSegment(
            content_type="audio/mpeg",
            mount_relative_path=rel_file,
            from_cache=False,
            chunks=(audio,),
        )
