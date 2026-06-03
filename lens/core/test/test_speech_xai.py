"""Tests for xAI speech backend HTTP client."""

from __future__ import annotations

import unittest
from unittest import mock

import httpx

from lens.core.speech.api.xai import XaiSpeechBackend
from lens.core.speech.backend import SpeechError
from lens.core.speech.spec import SpeechSpec


class XaiSpeechBackendTests(unittest.TestCase):
    def test_synthesize_success(self) -> None:
        spec = SpeechSpec(text="Hello", voice_id="eve", language="en")
        req = httpx.Request("POST", "https://api.x.ai/v1/tts")
        ok = httpx.Response(200, request=req, content=b"\xff\xfb\x90")

        backend = XaiSpeechBackend(
            api_key="k",
            base_url="https://api.x.ai/v1",
            timeout_seconds=30.0,
        )
        mock_client = mock.Mock()
        mock_client.post = mock.Mock(return_value=ok)
        mock_ctx = mock.Mock()
        mock_ctx.__enter__ = mock.Mock(return_value=mock_client)
        mock_ctx.__exit__ = mock.Mock(return_value=False)

        with mock.patch("lens.core.speech.api.xai.httpx.Client", return_value=mock_ctx):
            out = backend.synthesize(spec)

        self.assertEqual(out, b"\xff\xfb\x90")
        mock_client.post.assert_called_once()
        call_kw = mock_client.post.call_args
        self.assertTrue(str(call_kw[0][0]).endswith("/tts"))
        self.assertEqual(
            call_kw[1]["json"],
            {
                "text": "Hello",
                "language": "en",
                "text_normalization": True,
                "voice_id": "eve",
            },
        )
        self.assertIn("Authorization", call_kw[1]["headers"])

    def test_synthesize_http_error(self) -> None:
        spec = SpeechSpec(text="Hi", voice_id="eve", language="en")
        req = httpx.Request("POST", "https://api.x.ai/v1/tts")
        err = httpx.Response(401, request=req, text="unauthorized")

        backend = XaiSpeechBackend(
            api_key="k",
            base_url="https://api.x.ai/v1",
            timeout_seconds=30.0,
        )
        mock_client = mock.Mock()
        mock_client.post = mock.Mock(return_value=err)
        mock_ctx = mock.Mock()
        mock_ctx.__enter__ = mock.Mock(return_value=mock_client)
        mock_ctx.__exit__ = mock.Mock(return_value=False)

        with mock.patch("lens.core.speech.api.xai.httpx.Client", return_value=mock_ctx):
            with self.assertRaises(SpeechError) as ctx:
                backend.synthesize(spec)
        self.assertIn("401", str(ctx.exception))
        self.assertIn("unauthorized", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
