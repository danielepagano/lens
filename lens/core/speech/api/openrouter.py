"""OpenRouter Text-to-Speech (OpenAI-compatible Audio Speech API)."""

from __future__ import annotations

from typing import Any

import httpx

from lens.core.speech.backend import SpeechBackend, SpeechError
from lens.core.speech.spec import SpeechSpec


def _error_detail(resp: httpx.Response) -> str:
    text = resp.text.strip()
    if len(text) > 500:
        text = text[:500] + "…"
    return text


class OpenRouterSpeechBackend(SpeechBackend):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        model: str,
        response_format: str = "mp3",
        speed: float | None = None,
        provider: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._model = model
        self._response_format = response_format
        self._speed = speed
        self._provider = provider

    def synthesize(self, spec: SpeechSpec) -> bytes:
        url = f"{self._base_url}/audio/speech"
        payload: dict[str, Any] = {
            "model": self._model,
            "input": spec.text,
            "voice": spec.voice_id,
            "response_format": self._response_format,
        }
        if self._speed is not None:
            payload["speed"] = self._speed
        if self._provider is not None:
            payload["provider"] = self._provider

        timeout = httpx.Timeout(
            connect=10.0,
            read=self._timeout_seconds,
            write=30.0,
            pool=30.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as e:
            raise SpeechError(f"OpenRouter TTS request timed out: {e}") from e
        except httpx.RequestError as e:
            raise SpeechError(f"OpenRouter TTS request failed: {e}") from e

        if resp.status_code >= 400:
            raise SpeechError(
                f"OpenRouter TTS HTTP {resp.status_code}: {_error_detail(resp)}"
            )
        return resp.content

