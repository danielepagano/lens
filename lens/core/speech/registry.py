"""Load ``[[speech]]`` config blocks and resolve them to backend instances."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.core.speech.api.openrouter import OpenRouterSpeechBackend
from lens.core.speech.api.xai import XaiSpeechBackend
from lens.core.speech.backend import SpeechBackend, SpeechError
from lens.core.speech.grammars import (
    ensure_builtin_tts_grammars_registered,
    registered_tts_grammar_ids,
    resolve_tts_grammar,
)
from lens.core.speech.spec import SpeechDescriptor


def _load_speech_block(project_root: Path, speech_id: str | None) -> dict[str, Any]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise SpeechError("lens.toml not found; run 'lens init' first")
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_list = config.get("speech", [])
    speech_list: list[dict[str, Any]] = (
        cast(list[dict[str, Any]], raw_list) if isinstance(raw_list, list) else []
    )
    if not speech_list:
        raise SpeechError(
            "no [[speech]] entries found in lens.toml; "
            "add at least one speech backend configuration"
        )

    if speech_id is None or speech_id == "" or speech_id == "[default]":
        return speech_list[0]

    for entry in speech_list:
        if entry.get("id") == speech_id:
            return entry
    ids = [str(e.get("id", "")) for e in speech_list]
    raise SpeechError(
        f"no [[speech]] entry with id={speech_id!r} in lens.toml "
        f"(configured ids: {ids})"
    )


def _build_descriptor(raw: dict[str, Any]) -> SpeechDescriptor:
    api = str(raw.get("api", "")).strip()
    if not api:
        raise SpeechError("[[speech]] entry is missing required field 'api'")

    model = str(raw.get("model", "")).strip()
    grammar_raw = raw.get("grammar")
    grammar = (
        str(grammar_raw).strip()
        if grammar_raw is not None and str(grammar_raw).strip()
        else None
    )
    if grammar is None:
        # No explicit `grammar =`: if `api` happens to name a registered TTS
        # grammar (e.g. "xai"), use it as the default rather than requiring
        # the id to be spelled out twice. Backends whose api doesn't match a
        # grammar id (e.g. "openrouter") still need it set explicitly, since
        # markup style there depends on the underlying model, not the api.
        # speech_markup itself stays opt-in via `modalities.speech_markup`,
        # so defaulting the grammar here can't silently turn markup on.
        ensure_builtin_tts_grammars_registered()
        if api in registered_tts_grammar_ids():
            grammar = api
    refine_llm_raw = raw.get("refine_llm_id")
    refine_llm_id = (
        str(refine_llm_raw).strip()
        if refine_llm_raw is not None and str(refine_llm_raw).strip()
        else None
    )
    max_text_chars = int(raw.get("max_text_chars", 15000))
    timeout_seconds = float(raw.get("timeout_seconds", 120))
    descriptor_id = str(raw.get("id") or "[default]")
    dv_raw = raw.get("default_voice")
    default_voice = (
        str(dv_raw).strip()
        if dv_raw is not None and str(dv_raw).strip()
        else None
    )

    extras = {
        k: v
        for k, v in raw.items()
        if k
        not in {
            "id",
            "api",
            "model",
            "grammar",
            "refine_llm_id",
            "api_key_env",
            "base_url",
            "max_text_chars",
            "timeout_seconds",
            "default_voice",
        }
    }

    if grammar is not None:
        resolve_tts_grammar(grammar)

    return SpeechDescriptor(
        id=descriptor_id,
        api=api,
        model=model,
        grammar=grammar,
        refine_llm_id=refine_llm_id,
        max_text_chars=max_text_chars,
        timeout_seconds=timeout_seconds,
        default_voice=default_voice,
        extra=extras,
    )


def _resolve_api_key(raw: dict[str, Any]) -> str:
    env = str(raw.get("api_key_env", "")).strip()
    if not env:
        raise SpeechError(
            "[[speech]] entry is missing required field 'api_key_env' "
            "(name of the environment variable holding the API key)"
        )
    key = os.environ.get(env, "")
    if not key:
        raise SpeechError(
            f"environment variable {env!r} "
            f"(configured in [[speech]] api_key_env) is not set"
        )
    return key


def _build_backend(raw: dict[str, Any], descriptor: SpeechDescriptor) -> SpeechBackend:
    api = descriptor.api
    api_key = _resolve_api_key(raw)
    if api == "xai":
        base_url = str(raw.get("base_url", "https://api.x.ai/v1")).rstrip("/")
        return XaiSpeechBackend(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=descriptor.timeout_seconds,
        )
    if api == "openrouter":
        base_url = str(raw.get("base_url", "https://openrouter.ai/api/v1")).rstrip("/")
        if not descriptor.model.strip():
            raise SpeechError("[[speech]] entry is missing required field 'model'")
        response_format = str(descriptor.extra.get("response_format", "mp3")).strip() or "mp3"
        speed_raw = descriptor.extra.get("speed")
        speed: float | None = None
        if speed_raw is not None:
            try:
                speed = float(speed_raw)
            except (TypeError, ValueError) as e:
                raise SpeechError(f"invalid [[speech]] speed={speed_raw!r}") from e
        provider = descriptor.extra.get("provider")
        if provider is not None and not isinstance(provider, dict):
            raise SpeechError("[[speech]] provider must be a table/object when set")
        return OpenRouterSpeechBackend(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=descriptor.timeout_seconds,
            model=descriptor.model,
            response_format=response_format,
            speed=speed,
            provider=cast(dict[str, Any] | None, provider),
        )
    raise SpeechError(f"unknown speech api={api!r}; supported: 'xai', 'openrouter'")


def resolve(
    project_root: Path, speech_id: str | None = None
) -> tuple[SpeechDescriptor, SpeechBackend]:
    raw = _load_speech_block(project_root, speech_id)
    descriptor = _build_descriptor(raw)
    backend = _build_backend(raw, descriptor)
    return descriptor, backend


def is_speech_backend_ready(project_root: Path, speech_id: str | None = None) -> bool:
    """Return True if the default (or *speech_id*) ``[[speech]]`` entry resolves to a backend.

    Requires a usable API key in the environment. Used for aggregate flags such as stats.
    """
    try:
        resolve(project_root, speech_id)
    except SpeechError:
        return False
    return True


def load_descriptor(
    project_root: Path, speech_id: str | None = None
) -> SpeechDescriptor:
    raw = _load_speech_block(project_root, speech_id)
    return _build_descriptor(raw)
