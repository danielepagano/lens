"""Single-flight TTS chunk synthesis per cache file so prefetch and SSE playback can share work."""

from __future__ import annotations

import asyncio
from typing import Literal

from lens.core.commands.media_tts import (
    find_tts_chunk,
    read_mount_audio_bytes,
    synthesize_or_load_chunk_mp3,
)
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, get_mount_backend
from lens.core.speech.chunks import tts_cache_mount_prefix


class TtsChunkCoordinator:
    """Coordinates in-process tasks so at most one synthesis runs per chunk mp3 path."""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task[tuple[bytes, str, bool]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(session: ProjectSession, node: NarrativeNode, chunk_id: str) -> str:
        rel = f"{tts_cache_mount_prefix(node)}/{chunk_id}.mp3"
        return f"{session.project_root.resolve()}|{rel}"

    async def _run_synth(
        self,
        key: str,
        session: ProjectSession,
        node: NarrativeNode,
        *,
        line: int,
        chunk_id: str,
        voice_id: str | None,
        language: str,
        model_id: str | None,
    ) -> tuple[bytes, str, bool]:
        try:
            return await asyncio.to_thread(
                synthesize_or_load_chunk_mp3,
                session,
                node,
                line=line,
                chunk_id=chunk_id,
                voice_id=voice_id,
                language=language,
                model_id=model_id,
            )
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

    async def get_chunk_audio(
        self,
        session: ProjectSession,
        node: NarrativeNode,
        *,
        line: int,
        chunk_id: str,
        voice_id: str | None = None,
        language: str = "en",
        model_id: str | None = None,
    ) -> tuple[bytes, str, bool]:
        key = self._key(session, node, chunk_id)
        prefix = tts_cache_mount_prefix(node)
        rel_file = f"{prefix}/{chunk_id}.mp3"
        backend = get_mount_backend(session.project_root)
        if backend is None:
            raise LensException(
                "TTS requires [project] mount_point in lens.toml (same as other lens media)"
            )

        def read_if_cached() -> tuple[bytes, str, bool] | None:
            if backend.file_exists(rel_file):
                data, ctype = read_mount_audio_bytes(backend, rel_file)
                return (data, ctype, True)
            return None

        cached = await asyncio.to_thread(read_if_cached)
        if cached is not None:
            return cached

        async with self._lock:
            t = self._inflight.get(key)
            if t is None:
                t = asyncio.create_task(
                    self._run_synth(
                        key,
                        session,
                        node,
                        line=line,
                        chunk_id=chunk_id,
                        voice_id=voice_id,
                        language=language,
                        model_id=model_id,
                    )
                )
                self._inflight[key] = t

        return await t

    async def start_render_if_needed(
        self,
        session: ProjectSession,
        node: NarrativeNode,
        *,
        line: int,
        chunk_id: str,
        voice_id: str | None = None,
        language: str = "en",
        model_id: str | None = None,
    ) -> Literal["ready", "started", "rendering"]:
        await asyncio.to_thread(find_tts_chunk, node, line=line, chunk_id=chunk_id)

        key = self._key(session, node, chunk_id)
        prefix = tts_cache_mount_prefix(node)
        rel_file = f"{prefix}/{chunk_id}.mp3"
        backend = get_mount_backend(session.project_root)
        if backend is None:
            raise LensException(
                "TTS requires [project] mount_point in lens.toml (same as other lens media)"
            )

        def exists() -> bool:
            return backend.file_exists(rel_file)

        if await asyncio.to_thread(exists):
            return "ready"

        async with self._lock:
            if key in self._inflight:
                return "rendering"
            t = asyncio.create_task(
                self._run_synth(
                    key,
                    session,
                    node,
                    line=line,
                    chunk_id=chunk_id,
                    voice_id=voice_id,
                    language=language,
                    model_id=model_id,
                )
            )
            self._inflight[key] = t
        return "started"
