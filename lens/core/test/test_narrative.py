"""Unit tests for narrative node model and section operator."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.narrative import (
    NarrativeNode,
    find_unclosed_cursor_annotation,
    parse_segments,
)
from lens.core.project import get_active_narrative


def _make_narrative(tmp: Path, slug: str = "test") -> Path:
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    return narrative_dir


def _init_git(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )


class TestNodeResolution(unittest.TestCase):
    def test_root_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.md_path(), narrative / "_node.md")

    def test_root_node_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = p / "narrative" / "empty"
            narrative.mkdir(parents=True)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            with self.assertRaises(FileNotFoundError):
                node.md_path()

    def test_leaf_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node.md_path(), narrative / "event_1.md")

    def test_folder_node_md_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1").mkdir()
            (narrative / "event_1" / "_node.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node.md_path(), narrative / "event_1" / "_node.md")

    def test_folder_wins_over_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1").mkdir()
            (narrative / "event_1" / "_node.md").write_text("folder")
            (narrative / "event_1.md").write_text("leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertEqual(node.md_path(), narrative / "event_1" / "_node.md")

    def test_node_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertTrue(node.exists())
            missing = NarrativeNode(narrative_root=narrative, key_path=("missing",))
            self.assertFalse(missing.exists())


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
            self.assertEqual(node.child_keys(), ["ch1", "ch2"])

    def test_child_keys_leaf_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "a.md").write_text("a")
            (narrative / "b.md").write_text("b")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.child_keys(), ["a", "b"])

    def test_child_keys_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "folder").mkdir()
            (narrative / "folder" / "_node.md").write_text("# folder")
            (narrative / "leaf.md").write_text("leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(set(node.child_keys()), {"folder", "leaf"})

    def test_child_keys_ordered_by_annotation(self) -> None:
        """Children appear in the order their section annotations appear in the parent."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            # Create children out of alphabetical order: z, a, m
            for key in ("z", "a", "m"):
                (narrative / key).mkdir()
                (narrative / key / "_node.md").write_text(f"# {key}")
            # Parent references them in z, a, m order
            (narrative / "_node.md").write_text(
                "# root\n\n"
                "[section:z]: #\n"
                "[section:a]: #\n"
                "[section:m]: #\n"
            )
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.child_keys(), ["z", "a", "m"])

    def test_child_keys_unannotated_appended_sorted(self) -> None:
        """Filesystem children not in annotations are appended in sorted order."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            for key in ("b", "c", "a"):
                (narrative / key).mkdir()
                (narrative / key / "_node.md").write_text(f"# {key}")
            # Only 'b' is referenced in annotations
            (narrative / "_node.md").write_text(
                "# root\n\n[section:b]: #\n"
            )
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.child_keys(), ["b", "a", "c"])


class TestStructuralWarnings(unittest.TestCase):
    def test_file_and_folder_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "dup").mkdir()
            (narrative / "dup" / "_node.md").write_text("# dup")
            (narrative / "dup.md").write_text("dup leaf")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            warnings = node.structural_warnings()
            self.assertIn("both dup/ and dup.md exist; folder wins", warnings)


class TestNodeLeafFolder(unittest.TestCase):
    def test_root_is_not_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertFalse(node.is_leaf())

    def test_leaf_node_is_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertTrue(node.is_leaf())

    def test_folder_node_is_not_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "event_1").mkdir()
            (narrative / "event_1" / "_node.md").write_text("content")
            node = NarrativeNode(narrative_root=narrative, key_path=("event_1",))
            self.assertFalse(node.is_leaf())

    def test_to_folder_converts_leaf_to_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "ch1.md").write_text("# ch1\ncontent")
            (p / "lens.toml").write_text("[project]\n")
            _init_git(p)
            node = NarrativeNode(narrative_root=narrative, key_path=("ch1",))
            self.assertTrue(node.is_leaf())
            node.to_folder()
            self.assertFalse(node.is_leaf())
            self.assertTrue((narrative / "ch1" / "_node.md").exists())
            self.assertFalse((narrative / "ch1.md").exists())
            self.assertEqual(
                (narrative / "ch1" / "_node.md").read_text(),
                "# ch1\ncontent",
            )

    def test_to_leaf_converts_folder_to_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text("# ch1\ncontent")
            (p / "lens.toml").write_text("[project]\n")
            _init_git(p)
            node = NarrativeNode(narrative_root=narrative, key_path=("ch1",))
            self.assertFalse(node.is_leaf())
            node.to_leaf()
            self.assertTrue(node.is_leaf())
            self.assertFalse((narrative / "ch1").exists())
            self.assertTrue((narrative / "ch1.md").exists())
            self.assertEqual((narrative / "ch1.md").read_text(), "# ch1\ncontent")

    def test_to_leaf_rejects_if_folder_has_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text("# ch1")
            (narrative / "ch1" / "child").mkdir()
            (narrative / "ch1" / "child" / "_node.md").write_text("# child")
            node = NarrativeNode(narrative_root=narrative, key_path=("ch1",))
            with self.assertRaises(ValueError) as ctx:
                node.to_leaf()
            self.assertIn("other files", str(ctx.exception))

    def test_to_leaf_rejects_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            with self.assertRaises(ValueError) as ctx:
                node.to_leaf()
            self.assertIn("root", str(ctx.exception))

    def test_to_folder_rejects_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            node = NarrativeNode(narrative_root=narrative, key_path=())
            with self.assertRaises(ValueError) as ctx:
                node.to_folder()
            self.assertIn("root", str(ctx.exception))


class TestFrontMatter(unittest.TestCase):
    def test_no_front_matter_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\nContent")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.front_matter(), {})

    def test_valid_front_matter_at_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text(
                "[\n"
                "  kb_pins:\n"
                "    - place.needle_street\n"
                "    - place.capital_city\n"
                "  kb_unpin:\n"
                "    - front.the_demon_rises\n"
                "]: #\n\n"
                "# root\n\nContent"
            )
            node = NarrativeNode(narrative_root=narrative, key_path=())
            fm = node.front_matter()
            self.assertEqual(fm["kb_pins"], ["place.needle_street", "place.capital_city"])
            self.assertEqual(fm["kb_unpin"], ["front.the_demon_rises"])

    def test_front_matter_not_detected_in_middle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text(
                "# root\n\nContent\n\n"
                "[\n"
                "  key: value\n"
                "]: #\n\n"
                "More"
            )
            node = NarrativeNode(narrative_root=narrative, key_path=())
            self.assertEqual(node.front_matter(), {})

    def test_invalid_yaml_warns_and_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text(
                "[\n"
                "  invalid: yaml: [\n"
                "]: #\n\n"
                "# root"
            )
            node = NarrativeNode(narrative_root=narrative, key_path=())
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = node.front_matter()
            self.assertEqual(result, {})
            self.assertGreater(len(w), 0)
            self.assertIn("YAML", str(w[0].message))

    def test_front_matter_not_annotation_no_section_created(self) -> None:
        text = (
            "[\n"
            "  kb_pins: []\n"
            "]: #\n\n"
            "Content"
        )
        segs = parse_segments(text)
        for seg in segs:
            if seg.annotation is not None:
                self.assertNotEqual(seg.annotation.operator, "section")


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

    def test_multiple_annotations_with_text_interspersed(self) -> None:
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
        segs = parse_segments(text)
        self.assertEqual(len(segs), 5)
        self.assertEqual(segs[0].body.strip(), "Intro")
        self.assertIsNone(segs[0].annotation)
        assert segs[1].annotation is not None
        self.assertEqual(segs[1].annotation.operator, "section")
        self.assertEqual(segs[1].annotation.id, "ch1")
        self.assertEqual(segs[1].body.strip(), "Body one")
        self.assertIsNotNone(segs[1].close)
        assert segs[1].close is not None
        self.assertEqual(segs[1].close.operator, "section")
        self.assertEqual(segs[1].close.id, "ch1")
        self.assertEqual(segs[2].body.strip(), "Middle")
        self.assertIsNone(segs[2].annotation)
        assert segs[3].annotation is not None
        self.assertEqual(segs[3].annotation.id, "ch2")
        self.assertEqual(segs[3].body.strip(), "Body two")
        self.assertIsNotNone(segs[3].close)
        self.assertEqual(segs[4].body.strip(), "Outro")
        self.assertIsNone(segs[4].annotation)

    def test_close_must_match_operator_and_id(self) -> None:
        text = "[section:x]: #\nbody\n[/write:x]: #"
        segs = parse_segments(text)
        self.assertEqual(len(segs), 2)
        assert segs[1].annotation is not None
        self.assertEqual(segs[1].annotation.operator, "section")
        self.assertIsNone(segs[1].close)

    def test_unmatched_closing_discarded_starts_new_segment(self) -> None:
        text = "[section:x]: #\nbody\n[/section:y]: #\n\nafter"
        segs = parse_segments(text)
        self.assertEqual(len(segs), 3)
        assert segs[1].annotation is not None
        self.assertEqual(segs[1].annotation.id, "x")
        self.assertIsNone(segs[1].close)
        self.assertEqual(segs[1].body.strip(), "body")
        self.assertEqual(segs[2].body.strip(), "after")
        self.assertIsNone(segs[2].annotation)


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
            cursor = node.find_cursor()
            self.assertEqual(cursor.key_path, ())

    def test_cursor_one_level_deep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\n[section:ch1]: #\n")
            (narrative / "ch1").mkdir()
            (narrative / "ch1" / "_node.md").write_text("# ch1\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = node.find_cursor()
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
            cursor = node.find_cursor()
            self.assertEqual(cursor.key_path, ("ch1", "ch2"))

    def test_broken_reference_stops_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text("# root\n\n[section:missing]: #\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = node.find_cursor()
            self.assertEqual(cursor.key_path, ())

    def test_cursor_with_multi_line_section_annotation(self) -> None:
        """find_cursor must descend when parent has multi-line [section:id ...]: #."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            narrative = _make_narrative(p)
            (narrative / "_node.md").write_text(
                "# root\n\n[section:ch1\n  kb_pin: [location.inn]\n]: #\n"
            )
            (narrative / "ch1.md").write_text("# ch1\n")
            node = NarrativeNode(narrative_root=narrative, key_path=())
            cursor = node.find_cursor()
            self.assertEqual(cursor.key_path, ("ch1",))


class TestChildNode(unittest.TestCase):
    def test_child_node_construction(self) -> None:
        narrative = Path("/narrative/campaign")
        node = NarrativeNode(narrative_root=narrative, key_path=())
        child = node.child_node("event_1")
        self.assertEqual(child.key_path, ("event_1",))
        grandchild = child.child_node("scene_2")
        self.assertEqual(grandchild.key_path, ("event_1", "scene_2"))


class TestCursorPathStr(unittest.TestCase):
    def test_root_path(self) -> None:
        node = NarrativeNode(
            narrative_root=Path("/narrative/my-campaign"),
            key_path=(),
        )
        self.assertEqual(node.path_str(), "my-campaign")

    def test_nested_path(self) -> None:
        node = NarrativeNode(
            narrative_root=Path("/narrative/my-campaign"),
            key_path=("event_1", "scene_2"),
        )
        self.assertEqual(node.path_str(), "my-campaign / event_1 / scene_2")


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
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp, capture_output=True, check=True,
        )
        (tmp / "lens.toml").write_text('[project]\nnarrative = "test"\n')
        narrative = tmp / "narrative" / "test"
        narrative.mkdir(parents=True)
        (narrative / "_node.md").write_text("# test\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp, capture_output=True, check=True,
        )

    def test_section_start_creates_leaf_and_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            result = subprocess.run(
                ["lens", "section", "event_1"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            node_md = p / "narrative" / "test" / "_node.md"
            self.assertIn("[section:event_1]: #", node_md.read_text())
            section_md = p / "narrative" / "test" / "event_1.md"
            self.assertTrue(section_md.exists())
            self.assertEqual(section_md.read_text(), "")

    def test_section_start_with_pins_writes_front_matter_to_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            kb = p / "knowledge" / "location"
            kb.mkdir(parents=True)
            (kb / "castle-dorn.md").write_text("---\ntitle: Castle Dorn\n---\n")
            (kb / "capital-city.md").write_text("---\ntitle: Capital\n---\n")
            subprocess.run(["git", "add", "-A"], cwd=p, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "kb"],
                cwd=p, capture_output=True, check=True,
            )
            result = subprocess.run(
                [
                    "lens", "section", "castle-dorn",
                    "--pin", "location.castle-dorn",
                    "--pin", "location.capital-city+",
                    "--unpin", "location.capital-city",
                ],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            node_md = p / "narrative" / "test" / "_node.md"
            self.assertIn("kb_pin:", node_md.read_text())
            section_md = p / "narrative" / "test" / "castle-dorn.md"
            self.assertTrue(section_md.exists())
            text = section_md.read_text()
            self.assertIn("kb_pin:", text)
            self.assertIn("location.castle-dorn", text)
            self.assertIn("location.capital-city+", text)
            self.assertIn("kb_unpin:", text)
            self.assertIn("location.capital-city", text)

    def test_section_start_adds_blank_line_before_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self._make_project(p)
            (p / "narrative" / "test" / "_node.md").write_text("# test\nhello!")
            subprocess.run(["git", "add", "-A"], cwd=p, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "update"],
                cwd=p, capture_output=True, check=True,
            )
            result = subprocess.run(
                ["lens", "section", "ch1"],
                cwd=p,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
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
            narrative = get_active_narrative(p)
            assert narrative is not None
            from lens.core.operators.section import SectionOperator
            from lens.core.project import ProjectSession
            from lens.core.storage import Storage
            cursor = narrative.find_cursor()
            key = cursor.key_path[-1]
            parent = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=cursor.key_path[:-1],
            )
            rel = str(parent.md_path().relative_to(p))
            owner = SectionOperator.owner_id(key, rel)
            op = SectionOperator(Storage(p, owner=owner), narrative)
            async def _fake_generate_text(*args: Any, **kwargs: Any) -> str:
                from collections.abc import Awaitable, Callable
                from typing import cast

                if kwargs.get("operator_name") == "remember":
                    return ""
                on_preview = kwargs.get("on_preview")
                if on_preview is not None:
                    cb = cast(Callable[[str], Awaitable[None]], on_preview)
                    await cb("Section")
                    await cb(" summary.")
                return "Section summary."

            with patch("lens.core.operators.session.generate_text", new=_fake_generate_text):
                with contextlib.redirect_stdout(io.StringIO()):
                    asyncio.run(op.end(ProjectSession(p, p)))
            node_md = p / "narrative" / "test" / "_node.md"
            text = node_md.read_text()
            self.assertIn("[/section:event_1]: #", text)
            self.assertIn("Section summary.", text)

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
