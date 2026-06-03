"""Tests for ``lens.core.speech.synthesize_file``."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.speech.spec import SpeechDescriptor
from lens.core.speech.synthesize_file import synthesize_speech_bytes, synthesize_speech_mp3


class SynthesizeSpeechMp3Tests(unittest.TestCase):
    def test_writes_mp3_to_given_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lens.toml").write_text('[project]\nnarrative = "x"\n')
            session = ProjectSession(root, root)
            descriptor = SpeechDescriptor(
                id="[default]",
                api="xai",
                model="",
                grammar=None,
                max_text_chars=15000,
                timeout_seconds=60.0,
            )
            mock_backend = mock.Mock()
            mock_backend.synthesize = mock.Mock(return_value=b"fake-mp3")

            out_dir = root / "out"
            out_dir.mkdir()
            dest = out_dir / "out.mp3"
            old = os.getcwd()
            try:
                os.chdir(out_dir)
                with mock.patch(
                    "lens.core.speech.synthesize_file.speech_registry.resolve",
                    return_value=(descriptor, mock_backend),
                ):
                    path = synthesize_speech_mp3(
                        session.project_root,
                        "Hello there friend",
                        dest,
                    )
            finally:
                os.chdir(old)

            self.assertEqual(path.resolve(), dest.resolve())
            self.assertEqual(path.read_bytes(), b"fake-mp3")
            mock_backend.synthesize.assert_called_once()

    def test_voice_from_descriptor_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lens.toml").write_text('[project]\nnarrative = "x"\n')
            session = ProjectSession(root, root)
            descriptor = SpeechDescriptor(
                id="[default]",
                api="xai",
                model="",
                grammar=None,
                max_text_chars=15000,
                timeout_seconds=60.0,
                default_voice="sal",
            )
            mock_backend = mock.Mock()
            mock_backend.synthesize = mock.Mock(return_value=b"fake-mp3")

            old = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch(
                    "lens.core.speech.synthesize_file.speech_registry.resolve",
                    return_value=(descriptor, mock_backend),
                ):
                    synthesize_speech_bytes(session.project_root, "Hello")
            finally:
                os.chdir(old)

            spec = mock_backend.synthesize.call_args[0][0]
            self.assertEqual(spec.voice_id, "sal")

    def test_explicit_voice_overrides_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lens.toml").write_text('[project]\nnarrative = "x"\n')
            session = ProjectSession(root, root)
            descriptor = SpeechDescriptor(
                id="[default]",
                api="xai",
                model="",
                grammar=None,
                max_text_chars=15000,
                timeout_seconds=60.0,
                default_voice="sal",
            )
            mock_backend = mock.Mock()
            mock_backend.synthesize = mock.Mock(return_value=b"x")

            old = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch(
                    "lens.core.speech.synthesize_file.speech_registry.resolve",
                    return_value=(descriptor, mock_backend),
                ):
                    synthesize_speech_bytes(
                        session.project_root, "Hi", voice_id="leo"
                    )
            finally:
                os.chdir(old)

            spec = mock_backend.synthesize.call_args[0][0]
            self.assertEqual(spec.voice_id, "leo")

    def test_empty_text_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = ProjectSession(root, root)
            dest = root / "x.mp3"
            with self.assertRaises(LensException):
                synthesize_speech_mp3(session.project_root, "   ", dest)


if __name__ == "__main__":
    unittest.main()
