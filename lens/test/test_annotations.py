"""Unit tests for lens.annotations: strip_markdown_comments and parse_annotations."""

from __future__ import annotations

import unittest

from lens.annotations import parse_annotations, strip_markdown_comments


class TestStripMarkdownComments(unittest.TestCase):
    def test_empty_string(self) -> None:
        self.assertEqual(strip_markdown_comments(""), "")

    def test_preserves_plain_content(self) -> None:
        text = "Hello world\n\nMore text"
        self.assertEqual(strip_markdown_comments(text), text)

    def test_strips_single_line_comment(self) -> None:
        text = "Before\n[ op:write ]: #\nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_strips_minimal_comment(self) -> None:
        text = "Before\n[x]: #\nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_strips_multiline_comment(self) -> None:
        text = "Before\n[ \n  op:write\n  prompt: hey\n]: #\nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_strips_multiline_with_backslash_continuation(self) -> None:
        text = "Before\n[ \n  prompt: hey you! how about a \\\nmultiline prompt here?\n]: #\nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_strips_closing_tag_style(self) -> None:
        text = "Content\n[/op:write]: #\nMore"
        self.assertEqual(strip_markdown_comments(text), "Content\nMore")

    def test_strips_section_style(self) -> None:
        text = "Content\n[section:my_elaborate_aside]: #\nMore"
        self.assertEqual(strip_markdown_comments(text), "Content\nMore")

    def test_strips_comment_at_start(self) -> None:
        text = "[ front matter ]: #\nVisible content"
        self.assertEqual(strip_markdown_comments(text), "Visible content")

    def test_strips_comment_at_end(self) -> None:
        text = "Visible content\n[ trailing ]: #"
        self.assertEqual(strip_markdown_comments(text), "Visible content")

    def test_strips_multiple_comments(self) -> None:
        text = "A\n[ c1 ]: #\nB\n[ c2 ]: #\nC"
        self.assertEqual(strip_markdown_comments(text), "A\nB\nC")

    def test_preserves_link_syntax(self) -> None:
        text = "See [link text](https://example.com) for more."
        self.assertEqual(strip_markdown_comments(text), text)

    def test_preserves_reference_link_with_url(self) -> None:
        text = "[id]: http://example.com\nNot a comment"
        self.assertEqual(strip_markdown_comments(text), text)

    def test_strips_orphaned_comment_end(self) -> None:
        text = "Content\n]: #\nMore"
        self.assertEqual(strip_markdown_comments(text), "Content\nMore")

    def test_strips_indented_orphaned_comment_end(self) -> None:
        text = "Content\n  ]: #\nMore"
        self.assertEqual(strip_markdown_comments(text), "Content\nMore")

    def test_document_with_only_comments(self) -> None:
        text = "[ only ]: #\n[ comment ]: #"
        self.assertEqual(strip_markdown_comments(text), "")

    def test_comment_with_leading_whitespace(self) -> None:
        text = "Before\n  [ indented ]: #\nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_comment_with_trailing_whitespace(self) -> None:
        text = "Before\n[ comment ]: #  \nAfter"
        self.assertEqual(strip_markdown_comments(text), "Before\nAfter")

    def test_preserves_brackets_in_paragraph(self) -> None:
        text = "Array [0] and [1] are valid."
        self.assertEqual(strip_markdown_comments(text), text)

    def test_preserves_brackets_on_own_line(self) -> None:
        text = "[note text]\nMore content"
        self.assertEqual(strip_markdown_comments(text), text)

    def test_adjacent_comments(self) -> None:
        text = "[ first ]: #\n[ second ]: #\nContent"
        self.assertEqual(strip_markdown_comments(text), "Content")

    def test_text_interspersed_with_multiple_annotations(self) -> None:
        text = (
            "Intro\n\n"
            "[section:ch1]: #\n"
            "Body one\n\n"
            "[/section:ch1]: #\n\n"
            "Middle\n\n"
            "[section:ch2]: #\n"
            "Body two\n\n"
            "[/section:ch2]: #\n\n"
            "Outro"
        )
        expected = "Intro\n\nBody one\n\n\nMiddle\n\nBody two\n\n\nOutro"
        self.assertEqual(strip_markdown_comments(text), expected)


class TestAnnotationParsing(unittest.TestCase):
    def test_single_line_open(self) -> None:
        text = "[section:my_aside]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 1)
        self.assertEqual(anns[0].operator, "section")
        self.assertEqual(anns[0].id, "my_aside")
        self.assertFalse(anns[0].closing)
        self.assertFalse(anns[0].self_closing)

    def test_closing_annotation(self) -> None:
        text = "[/section:my_aside]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 1)
        self.assertTrue(anns[0].closing)
        self.assertEqual(anns[0].operator, "section")
        self.assertEqual(anns[0].id, "my_aside")

    def test_self_closing(self) -> None:
        text = "[chat:notes/]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 1)
        self.assertTrue(anns[0].self_closing)
        self.assertEqual(anns[0].operator, "chat")
        self.assertEqual(anns[0].id, "notes")

    def test_multiline_yaml_params(self) -> None:
        text = "[write\n  prompt: hello\n  kb_pins:\n    - x.y\n]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 1)
        self.assertEqual(anns[0].operator, "write")
        self.assertIn("prompt", anns[0].params)
        self.assertEqual(anns[0].params.get("prompt"), "hello")

    def test_plain_comment_not_parsed(self) -> None:
        text = "Before\n[ arbitrary text ]: #\nAfter"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_front_matter_not_parsed(self) -> None:
        text = "[ \n  kb_pins: []\n]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_reference_link_not_parsed(self) -> None:
        text = "[id]: http://example.com"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_inline_link_not_parsed(self) -> None:
        text = "See [link](https://example.com) for more."
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_brackets_in_paragraph_not_parsed(self) -> None:
        text = "Array [0] and [1] are valid."
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_malformed_annotation_missing_end_not_parsed(self) -> None:
        text = "[section:my_aside"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_operator_with_space_not_parsed(self) -> None:
        text = "[ section:my_aside]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_operator_with_space_after_colon_not_parsed(self) -> None:
        text = "[section: my_aside]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 0)

    def test_mixed_annotations_and_plain_comments(self) -> None:
        text = "A\n[section:x]: #\nB\n[ c2 ]: #\nC\n[/section:x]: #"
        anns = parse_annotations(text)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].operator, "section")
        self.assertEqual(anns[0].id, "x")
        self.assertFalse(anns[0].closing)
        self.assertTrue(anns[1].closing)

    def test_annotations_stripped_like_comments(self) -> None:
        text = "Visible\n[section:ch1]: #\nMore"
        self.assertEqual(strip_markdown_comments(text), "Visible\nMore")
