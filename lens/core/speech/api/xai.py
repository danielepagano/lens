"""xAI Text-to-Speech (``POST /v1/tts``)."""

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


class XaiSpeechBackend(SpeechBackend):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def synthesize(self, spec: SpeechSpec) -> bytes:
        url = f"{self._base_url}/tts"
        payload: dict[str, Any] = {
            "text": spec.text,
            "language": spec.language,
            "text_normalization": True,
        }
        if spec.voice_id:
            payload["voice_id"] = spec.voice_id

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
            raise SpeechError(f"xAI TTS request timed out: {e}") from e
        except httpx.RequestError as e:
            raise SpeechError(f"xAI TTS request failed: {e}") from e

        if resp.status_code >= 400:
            raise SpeechError(
                f"xAI TTS HTTP {resp.status_code}: {_error_detail(resp)}"
            )
        return resp.content
