"""Tests for visual-novel playback sequence (TTS-aligned chunks + images)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode
from lens.core.speech.chunks import chunks_for_node_text
from lens.core.commands.attach import build_embed, build_layered_embed
from lens.core.speech.playback_sequence import (
    PlaybackImageItem,
    PlaybackLayeredItem,
    PlaybackTextItem,
    PlaybackVideoItem,
    parse_attach_video_line,
    parse_composite_line,
    parse_standalone_image_line,
    playback_items_for_node,
)


class TestStandaloneImageLine(unittest.TestCase):
    def test_parses_image(self) -> None:
        self.assertEqual(
            parse_standalone_image_line("  ![hero](media/a.png)  "),
            ("hero", "media/a.png"),
        )

    def test_rejects_plain_link(self) -> None:
        self.assertIsNone(parse_standalone_image_line("[t](https://x)"))


class TestAttachVideoPlaybackLine(unittest.TestCase):
    def test_parse_matches_build_embed_output(self) -> None:
        line = build_embed("p/clip.mp4", ".mp4")
        self.assertEqual(parse_attach_video_line(line), ("clip.mp4", "p/clip.mp4"))

    def test_parse_rejects_non_attach_shapes(self) -> None:
        self.assertIsNone(parse_attach_video_line("not a tag"))
        self.assertIsNone(parse_attach_video_line('<video src="/wrong/x.mp4" controls playsinline></video>'))


class TestCompositePlaybackLine(unittest.TestCase):
    def test_parse_matches_build_layered_embed_output(self) -> None:
        line = build_layered_embed("bg/scene.jpg", "fg/amy.png")
        self.assertEqual(
            parse_composite_line(line),
            ("bg/scene.jpg", "scene.jpg", "fg/amy.png", "amy.png"),
        )

    def test_parse_rejects_non_composite_shapes(self) -> None:
        self.assertIsNone(parse_composite_line("not a tag"))
        self.assertIsNone(parse_composite_line('<div class="other"><img src="x"></div>'))
        self.assertIsNone(parse_composite_line(build_embed("p/clip.mp4", ".mp4")))


def _node(tmp: Path, rel_md: str, body: str) -> NarrativeNode:
    narrative_root = tmp / "narrative" / "story"
    narrative_root.mkdir(parents=True)
    p = narrative_root / rel_md
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    key_path: tuple[str, ...]
    if rel_md == "_node.md":
        key_path = ()
    else:
        parts = Path(rel_md).parts
        stem = parts[-1][:-3] if parts[-1].endswith(".md") else parts[-1]
        key_path = tuple(parts[:-1] + (stem,))
    return NarrativeNode(narrative_root=narrative_root, key_path=key_path)


class TestPlaybackOrdering(unittest.TestCase):
    def test_prose_image_prose_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "m"\n')
            (tmp / "m").mkdir()
            body = "First line.\n\n![sc](x.png)\n\nSecond line.\n"
            node = _node(tmp, "scene.md", body)
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 3)
            it0 = items[0]
            it1 = items[1]
            it2 = items[2]
            assert isinstance(it0, PlaybackTextItem)
            assert isinstance(it1, PlaybackImageItem)
            assert isinstance(it2, PlaybackTextItem)
            self.assertEqual(it0.text, "First line.")
            self.assertFalse(it0.ai_gen)
            self.assertEqual(it1.url, "x.png")
            self.assertEqual(it2.text, "Second line.")
            self.assertFalse(it2.ai_gen)

    def test_prose_attach_video_embed_prose_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "m"\n')
            (tmp / "m").mkdir()
            vid = build_embed("loop.mp4", ".mp4")
            body = "First line.\n\n" + vid + "\n\nSecond line.\n"
            node = _node(tmp, "scene.md", body)
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 3)
            it0 = items[0]
            it1 = items[1]
            it2 = items[2]
            assert isinstance(it0, PlaybackTextItem)
            assert isinstance(it1, PlaybackVideoItem)
            assert isinstance(it2, PlaybackTextItem)
            self.assertEqual(it0.text, "First line.")
            self.assertEqual(it1.url, "loop.mp4")
            self.assertEqual(it1.alt, "loop.mp4")
            self.assertEqual(it2.text, "Second line.")

    def test_alignment_with_chunks_for_node_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            body = "Short.\n\nLong prose " + ("word " * 80) + "end.\n"
            node = _node(tmp, "a.md", body)
            from_chunks = chunks_for_node_text(body)
            items = [x for x in playback_items_for_node(node, tmp) if isinstance(x, PlaybackTextItem)]
            self.assertEqual([(x.id, x.line, x.text) for x in items], [(c.id, c.source_kept_line_1, c.raw_line) for c in from_chunks])

    def test_omits_fenced_blocks_and_orphan_tool_call_fence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            body = (
                "Narration.\n\n"
                "```yaml\n"
                "x: 1\n"
                "```\n\n"
                "```tool-call\n\n"
                "After.\n"
            )
            node = _node(tmp, "a.md", body)
            texts = [x.text for x in playback_items_for_node(node, tmp) if isinstance(x, PlaybackTextItem)]
            self.assertEqual(texts, ["Narration.", "After."])

    def test_tts_cached_false_without_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "m"\n')
            (tmp / "m").mkdir()
            node = _node(tmp, "a.md", "Hello.\n")
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 1)
            assert isinstance(items[0], PlaybackTextItem)
            self.assertIsNone(items[0].tts_cached)
            self.assertFalse(items[0].ai_gen)

    def test_tts_cached_bool_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "m"\n')
            mount = tmp / "m"
            mount.mkdir()
            fm = "[\n    tts_cached: 1\n]: #\n\n"
            node = _node(tmp, "a.md", fm + "Hello.\n")
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 1)
            assert isinstance(items[0], PlaybackTextItem)
            self.assertFalse(items[0].tts_cached)
            self.assertFalse(items[0].ai_gen)
            from lens.core.speech.chunks import TTS_CHUNK_REVISION, chunk_id, tts_cache_mount_prefix

            cid = chunk_id(TTS_CHUNK_REVISION, "Hello.")
            prefix = tts_cache_mount_prefix(node)
            pdir = mount
            for part in prefix.split("/"):
                pdir = pdir / part
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / f"{cid}.mp3").write_bytes(b"id3")
            items2 = playback_items_for_node(node, tmp)
            assert isinstance(items2[0], PlaybackTextItem)
            self.assertTrue(items2[0].tts_cached)
            self.assertFalse(items2[0].ai_gen)

    def test_lines_are_raw_on_disk_with_html_comment_and_fence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            body = (
                "Hello.\n"
                "\n"
                "<!--\n"
                "secret\n"
                "secret\n"
                "-->\n"
                "More.\n"
                "\n"
                "```python\n"
                "foo()\n"
                "```\n"
                "\n"
                "Done.\n"
            )
            node = _node(tmp, "a.md", body)
            items = [x for x in playback_items_for_node(node, tmp) if isinstance(x, PlaybackTextItem)]
            self.assertEqual([x.text for x in items], ["Hello.", "More.", "Done."])
            self.assertEqual([x.line for x in items], [1, 7, 13])

    def test_image_line_is_raw_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            body = (
                "<!--\n"
                "secret\n"
                "-->\n"
                "Hello.\n"
                "\n"
                "![sc](x.png)\n"
                "\n"
                "Tail.\n"
            )
            node = _node(tmp, "a.md", body)
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 3)
            it_text = items[0]
            it_image = items[1]
            it_tail = items[2]
            assert isinstance(it_text, PlaybackTextItem)
            assert isinstance(it_image, PlaybackImageItem)
            assert isinstance(it_tail, PlaybackTextItem)
            self.assertEqual(it_text.line, 4)
            self.assertEqual(it_image.line, 6)
            self.assertEqual(it_tail.line, 8)

    def test_prose_composite_embed_prose_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "m"\n')
            (tmp / "m").mkdir()
            composite = build_layered_embed("bg/scene.jpg", "fg/amy.png")
            body = "First line.\n\n" + composite + "\n\nSecond line.\n"
            node = _node(tmp, "scene.md", body)
            items = playback_items_for_node(node, tmp)
            self.assertEqual(len(items), 3)
            it0, it1, it2 = items
            assert isinstance(it0, PlaybackTextItem)
            assert isinstance(it1, PlaybackLayeredItem)
            assert isinstance(it2, PlaybackTextItem)
            self.assertEqual(it0.text, "First line.")
            self.assertEqual(it1.bg_url, "bg/scene.jpg")
            self.assertEqual(it1.bg_alt, "scene.jpg")
            self.assertEqual(it1.fg_url, "fg/amy.png")
            self.assertEqual(it1.fg_alt, "amy.png")
            self.assertEqual(it2.text, "Second line.")

    def test_ai_gen_true_inside_operator_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            body = (
                "User line.\n"
                "[write:1]: #\n"
                "AI line 1.\n"
                "AI line 2.\n"
                "[/write:1]: #\n"
                "User tail.\n"
            )
            node = _node(tmp, "a.md", body)
            items = [x for x in playback_items_for_node(node, tmp) if isinstance(x, PlaybackTextItem)]
            self.assertEqual([x.text for x in items], ["User line.", "AI line 1.", "AI line 2.", "User tail."])
            self.assertEqual([x.ai_gen for x in items], [False, True, True, False])


if __name__ == "__main__":
    unittest.main()
