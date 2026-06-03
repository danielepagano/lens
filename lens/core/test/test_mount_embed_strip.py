"""Tests for stripping attach-style mount embeds from LLM-facing text."""

from __future__ import annotations

import unittest

from lens.core.mount_embed_strip import (
    line_is_standalone_lens_mount_attachment,
    strip_standalone_lens_mount_attachment_lines,
)


class TestStandaloneMountAttachment(unittest.TestCase):
    def test_image_line(self) -> None:
        s = "![hero.jpg](/mount/file/images/hero.jpg)"
        self.assertTrue(line_is_standalone_lens_mount_attachment(s))

    def test_encoded_path_in_markdown_link(self) -> None:
        s = "[a b](/mount/file/folder/hello%20world.png)"
        self.assertTrue(line_is_standalone_lens_mount_attachment(s))

    def test_preview_md_line(self) -> None:
        s = "[readme.txt](/mount/preview/notes/readme.txt)"
        self.assertTrue(line_is_standalone_lens_mount_attachment(s))

    def test_video_line_matches_attach_html(self) -> None:
        s = (
            '<video src="/mount/file/clips/x.mp4" controls playsinline '
            'webkit-playsinline preload="metadata" style="max-width:100%"></video>'
        )
        self.assertTrue(line_is_standalone_lens_mount_attachment(s))

    def test_padded_line_still_matches(self) -> None:
        s = "  ![x](/mount/file/x.jpg)  "
        self.assertTrue(line_is_standalone_lens_mount_attachment(s))

    def test_inline_mount_image_in_prose_not_stripped_as_line(self) -> None:
        self.assertFalse(
            line_is_standalone_lens_mount_attachment(
                'See ![x](/mount/file/x.jpg) here.'
            )
        )

    def test_external_image_standalone_kept(self) -> None:
        self.assertFalse(
            line_is_standalone_lens_mount_attachment("![](https://example.com/a.png)")
        )

    def test_strip_multiline(self) -> None:
        raw = (
            "One\n"
            "![x](/mount/file/a.png)\n\n"
            "Two\n"
            "[doc.pdf](/mount/file/d/doc.pdf)\n"
        )
        self.assertEqual(
            strip_standalone_lens_mount_attachment_lines(raw),
            "One\n\nTwo\n",
        )

    def test_no_mount_returns_same_object(self) -> None:
        s = "Just prose\nsecond line\n"
        self.assertIs(strip_standalone_lens_mount_attachment_lines(s), s)


if __name__ == "__main__":
    unittest.main()
