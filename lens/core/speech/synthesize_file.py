"""Internal: write synthesized speech bytes to a path (core speech pipeline only)."""

from __future__ import annotations

from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.speech import registry as speech_registry
from lens.core.speech.spec import SpeechDescriptor, SpeechSpec


def _enforce_text_length(text: str, *, limit: int) -> None:
    n = len(text)
    if n > limit:
        raise LensException(
            f"speech text too long: {n} characters > max_text_chars={limit}"
        )


def _resolve_voice_id(voice_id: str | None, descriptor: SpeechDescriptor) -> str:
    if voice_id is not None and voice_id.strip():
        return voice_id.strip()
    if descriptor.default_voice and descriptor.default_voice.strip():
        return descriptor.default_voice.strip()
    return "eve"


def synthesize_speech_bytes(
    project_root: Path,
    text: str,
    *,
    voice_id: str | None = None,
    language: str = "en",
    model_id: str | None = None,
) -> bytes:
    stripped = text.strip()
    if not stripped:
        raise LensException("speech text is empty")

    descriptor, backend = speech_registry.resolve(project_root, model_id)
    _enforce_text_length(stripped, limit=descriptor.max_text_chars)
    effective_voice = _resolve_voice_id(voice_id, descriptor)
    spec = SpeechSpec(text=stripped, voice_id=effective_voice, language=language)
    return backend.synthesize(spec)


def synthesize_speech_mp3(
    project_root: Path,
    text: str,
    out_path: Path,
    *,
    voice_id: str | None = None,
    language: str = "en",
    model_id: str | None = None,
) -> Path:
    audio = synthesize_speech_bytes(
        project_root,
        text,
        voice_id=voice_id,
        language=language,
        model_id=model_id,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    return out_path
