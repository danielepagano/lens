"""Unit tests for narrative node model and section operator."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.narrative import (
    NarrativeNode,
    child_keys,
    child_node,
    cursor_path_str,
    find_cursor,
    find_unclosed_cursor_annotation,
    get_active_narrative,
    node_exists,
    node_md_path,
    parse_annotations,
    parse_segments,
    structural_warnings,
)


def _make_narrative(tmp: Path, slug: str = "test") -> Path:
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    return narrative_dir


class TestNodeResolution(unittest.TestCase):
    def test_root_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node_md_path(node), narrative / "_node.md")

    def test_root_node_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = p / "narrative" / "empty"
            narrative.mkdir(parents=True)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertIsNone(node_md_path(node))

    def test_leaf_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node_md_path(node), narrative / "event_1.md")

    def test_folder_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1").mkdir()
            (narrative / "event_1" / "_node.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node_md_path(node), narrative / "event_1" / "_node.md")

    def test_folder_wins_over_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1").mkdir()
            (narrative / "event_1" / "_node.md").write_text("folder")
            (narrative / "event_1.md").write_text("leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node_md_path(node), narrative / "event_1" / "_node.md")

    def test_node_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertTrue(node_exists(node))
            missing = NarrativeNode(narrative_root=narrative, key_path=("missing",))
            self.assertFalse(node_exists(missing))


class TestChildDiscovery(unittest.TestCase):
    def test_child_keys_folder_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text("# ch1")
            (narrative / "ch2").mkdir()
            (narrative / "ch2" / "_node.md").write_text("# ch2")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(child_keys(node), ["ch1", "ch2"])

    def test_child_keys_leaf_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "a.md").write_text("a")
            (narrative / "b.md").write_text("b")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(child_keys(node), ["a", "b"])

    def test_child_keys_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "folder").mkdir()
            (narrative / "folder" / "_node.md").write_text("# folder")
            (narrative / "leaf.md").write_text("leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(set(child_keys(node)), {"folder", "leaf"})


class TestStructuralWarnings(unittest.TestCase):
    def test_file_and_folder_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "dup").mkdir()
            (narrative / "dup" / "_node.md").write_text("# dup")
            (narrative / "dup.md").write_text("dup leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            warnings = structural_warnings(node)
            self.assertIn("both dup/ and dup.md exist; folder wins", warnings)


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


class TestSegmentParsing(unittest.TestCase):
    def test_paired_open_close(self) -> None:
        text = "[section:x]: #\nbody\n\n[/section:x]: #"
        segs = parse_segments(text)
        self.assertEqual(len(segs), 2)
        self.assertIsNone(segs[0].annotation)
        self.assertEqual(segs[0].body, "")
        self.assertIsNotNone(segs[1].annotation)
        assert segs[1].annotation is not None
        self.assertEqual(segs[1].annotation.operator, "section")
        self.assertEqual(segs[1].body.strip(), "body")
        self.assertIsNotNone(segs[1].close)

    def test_unclosed_at_end(self) -> None:
        text = "intro\n\n[section:x]: #\nmore"
        segs = parse_segments(text)
        self.assertEqual(len(segs), 2)
        self.assertIsNone(segs[0].annotation)
        self.assertEqual(segs[0].body.strip(), "intro")
        self.assertIsNotNone(segs[1].annotation)
        self.assertIsNone(segs[1].close)
        self.assertEqual(segs[1].body.strip(), "more")

    def test_free_text_at_end(self) -> None:
        text = "[section:x]: #\nbody\n\n[/section:x]: #\n\ntrailing text"
        segs = parse_segments(text)
        self.assertEqual(len(segs), 3)
        self.assertIsNone(segs[2].annotation)
        self.assertEqual(segs[2].body.strip(), "trailing text")


class TestFindUnclosedCursorAnnotation(unittest.TestCase):
    def test_returns_last_unclosed_only(self) -> None:
        text = "[section:a]: #\n\n[/section:a]: #\n\n[section:b]: #\n"
        ann = find_unclosed_cursor_annotation(text)
        self.assertIsNotNone(ann)
        assert ann is not None
        self.assertEqual(ann.id, "b")

    def test_returns_none_for_trailing_text(self) -> None:
        text = "[section:x]: #\n\n[/section:x]: #\n\nfree text"
        ann = find_unclosed_cursor_annotation(text)
        self.assertIsNone(ann)

    def test_returns_none_for_empty(self) -> None:
        self.assertIsNone(find_unclosed_cursor_annotation(""))


class TestFindCursor(unittest.TestCase):
    def test_root_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = find_cursor(node)
            self.assertEqual(cursor.key_path, ())

    def test_cursor_one_level_deep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\n[section:ch1]: #\n")
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text("# ch1\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = find_cursor(node)
            self.assertEqual(cursor.key_path, ("ch1",))

    def test_cursor_two_levels_deep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\n[section:ch1]: #\n")
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text(
                "# ch1\n\n[section:ch2]: #\n"
            )
            (narrative / "ch1" / "ch2").mkdir()
            (narrative / "ch1" / "ch2" / "_node.md").write_text("# ch2\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = find_cursor(node)
            self.assertEqual(cursor.key_path, ("ch1", "ch2"))

    def test_broken_reference_stops_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\n[section:missing]: #\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = find_cursor(node)
            self.assertEqual(cursor.key_path, ())


class TestChildNode(unittest.TestCase):
    def test_child_node_construction(self) -> None:
        narrative = Path("/narrative/campaign")
        node = NarrativeNode(narrative_root=narrative, key_path=())
        child = child_node(node, "event_1")
        self.assertEqual(child.key_path, ("event_1",))
        grandchild = child_node(child, "scene_2")
        self.assertEqual(grandchild.key_path, ("event_1", "scene_2"))


class TestCursorPathStr(unittest.TestCase):
    def test_root_path(self) -> None:
        node = NarrativeNode(
            narrative_root=Path("/narrative/my-campaign"),
            key_path=(),
        )
        self.assertEqual(cursor_path_str(node), "my-campaign")

    def test_nested_path(self) -> None:
        node = NarrativeNode(
            narrative_root=Path("/narrative/my-campaign"),
            key_path=("event_1", "scene_2"),
        )
        self.assertEqual(cursor_path_str(node), "my-campaign / event_1 / scene_2")


class TestGetActiveNarrative(unittest.TestCase):
    def test_returns_none_without_lens_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(get_active_narrative(Path(tmp)))

    def test_returns_none_without_narrative_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text("[project]\n")
            (p / "narrative").mkdir()
            self.assertIsNone(get_active_narrative(p))

    def test_returns_node_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nnarrative = "campaign"\n')
            narrative_dir = p / "narrative" / "campaign"
            narrative_dir.mkdir(parents=True)
            (narrative_dir / "_node.md").write_text("# campaign\n")
            node = get_active_narrative(p)
            self.assertIsNotNone(node)
            assert node is not None
            self.assertEqual(node.narrative_root, narrative_dir)
            self.assertEqual(node.key_path, ())


class TestSectionOperator(unittest.TestCase):
    def _make_project(self, tmp: Path) -> None:
        (tmp / "lens.toml").write_text('[project]\nnarrative = "test"\n')
        narrative = tmp / "narrative" / "test"
        narrative.mkdir(parents=True)
        (narrative / "_node.md").write_text("# test\n")

    def test_section_start_creates_folder_and_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            result = subprocess.run(
                ["lens", "section", "event_1"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            node_md = p / "narrative" / "test" / "_node.md"
            self.assertIn("[section:event_1]: #", node_md.read_text())
            section_dir = p / "narrative" / "test" / "event_1"
            self.assertTrue(section_dir.is_dir())
            self.assertTrue((section_dir / "_node.md").exists())
            self.assertIn("# event_1", (section_dir / "_node.md").read_text())

    def test_section_start_adds_blank_line_before_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            (p / "narrative" / "test" / "_node.md").write_text("# test\nhello!")
            result = subprocess.run(
                ["lens", "section", "ch1"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            text = (p / "narrative" / "test" / "_node.md").read_text()
            self.assertIn("hello!\n\n[section:ch1]: #", text)

    def test_section_end_closes_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            subprocess.run(
                ["lens", "section", "event_1"],
                cwd=p,
                capture_output=True,
                check=True,
            )
            result = subprocess.run(
                ["lens", "section", "--end"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            node_md = p / "narrative" / "test" / "_node.md"
            text = node_md.read_text()
            self.assertIn("[/section:event_1]: #", text)
            self.assertIn("summary placeholder", text)
            self.assertIn("> _(", text)

    def test_section_end_at_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            result = subprocess.run(
                ["lens", "section", "--end"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no open section", result.stderr)
