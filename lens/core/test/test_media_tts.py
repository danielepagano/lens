"""Tests for node TTS playback iterator."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.commands.media_tts import iter_node_tts_playback
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.speech.spec import SpeechDescriptor


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    (root / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=root, capture_output=True, check=True)


class TestIterNodeTtsPlayback(unittest.TestCase):
    def test_no_eligible_lines_yields_nothing_without_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git_init(root)
            (root / "lens.toml").write_text('[project]\nnarrative = "camp"\n')
            nar = root / "narrative" / "camp"
            nar.mkdir(parents=True)
            (nar / "_node.md").write_text(
                "[\n]: #\n\n"
                "<!-- x -->\n"
                "\n"
                "![a](b)\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "n"],
                cwd=root,
                capture_output=True,
                check=True,
            )

            session = ProjectSession(root, root)
            node = NarrativeNode(narrative_root=nar, key_path=())
            self.assertEqual(list(iter_node_tts_playback(session, node)), [])

    def test_slice_beyond_file_yields_nothing_without_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git_init(root)
            (root / "lens.toml").write_text('[project]\nnarrative = "camp"\n')
            nar = root / "narrative" / "camp"
            nar.mkdir(parents=True)
            (nar / "_node.md").write_text("[\n]: #\n\nHello.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "n"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            session = ProjectSession(root, root)
            node = NarrativeNode(narrative_root=nar, key_path=())
            out = list(
                iter_node_tts_playback(
                    session,
                    node,
                    line_start_1=99,
                    line_end_1=100,
                )
            )
            self.assertEqual(out, [])

    def test_second_playback_pass_reads_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git_init(root)
            (root / "media").mkdir()
            (root / "lens.toml").write_text(
                '[project]\nnarrative = "camp"\nmount_point = "media"\n'
            )
            nar = root / "narrative" / "camp"
            nar.mkdir(parents=True)
            (nar / "_node.md").write_text(
                "[\n]: #\n\n"
                "First line.\n"
                "Second line.\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "n"],
                cwd=root,
                capture_output=True,
                check=True,
            )

            session = ProjectSession(root, root)
            node = NarrativeNode(narrative_root=nar, key_path=())
            descriptor = SpeechDescriptor(
                id="[default]",
                api="xai",
                model="",
                grammar=None,
                max_text_chars=15000,
                timeout_seconds=60.0,
            )
            mock_backend = mock.Mock()
            mock_backend.synthesize = mock.Mock(return_value=b"x")

            with mock.patch(
                "lens.core.speech.synthesize_file.speech_registry.resolve",
                return_value=(descriptor, mock_backend),
            ):
                first = list(iter_node_tts_playback(session, node))
                second = list(iter_node_tts_playback(session, node))

            self.assertEqual(len(first), 2)
            self.assertFalse(first[0].from_cache)
            self.assertFalse(first[1].from_cache)
            self.assertTrue(second[0].from_cache)
            self.assertTrue(second[1].from_cache)
            self.assertEqual(mock_backend.synthesize.call_count, 2)
            cache_dir = root / "media" / "tts-cache" / "camp"
            mp3s = list(cache_dir.glob("*.mp3"))
            self.assertEqual(len(mp3s), 2)

    def test_requires_mount_when_eligible_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git_init(root)
            (root / "lens.toml").write_text('[project]\nnarrative = "camp"\n')
            nar = root / "narrative" / "camp"
            nar.mkdir(parents=True)
            (nar / "_node.md").write_text("[\n]: #\n\nHello world.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "n"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            session = ProjectSession(root, root)
            node = NarrativeNode(narrative_root=nar, key_path=())
            with self.assertRaises(LensException) as ctx:
                list(iter_node_tts_playback(session, node))
            self.assertIn("mount", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
