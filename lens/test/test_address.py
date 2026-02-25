"""Unit tests for lens.address: NarrativeAddress parsing and conversion."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.address import NarrativeAddress
from lens.narrative import NarrativeNode


def _make_project(tmp: Path, slug: str = "test") -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


class TestNarrativeAddressParse(unittest.TestCase):
    def test_cursor_shorthand(self) -> None:
        addr = NarrativeAddress.parse("/@cursor")
        self.assertTrue(addr.cursor)
        self.assertIsNone(addr.narrative)
        self.assertEqual(addr.key_path, ())
        self.assertEqual(str(addr), "/@cursor")

    def test_relative_root(self) -> None:
        addr = NarrativeAddress.parse("/")
        self.assertIsNone(addr.narrative)
        self.assertEqual(addr.key_path, ())
        self.assertEqual(str(addr), "/")

    def test_relative_path(self) -> None:
        addr = NarrativeAddress.parse("/event_1")
        self.assertIsNone(addr.narrative)
        self.assertEqual(addr.key_path, ("event_1",))
        self.assertEqual(str(addr), "/event_1")

    def test_relative_nested(self) -> None:
        addr = NarrativeAddress.parse("/event_1/scene_2")
        self.assertIsNone(addr.narrative)
        self.assertEqual(addr.key_path, ("event_1", "scene_2",))
        self.assertEqual(str(addr), "/event_1/scene_2")

    def test_explicit_narrative_root(self) -> None:
        addr = NarrativeAddress.parse("campaign")
        self.assertEqual(addr.narrative, "campaign")
        self.assertEqual(addr.key_path, ())
        self.assertEqual(str(addr), "campaign")

    def test_explicit_narrative_path(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1/scene_2")
        self.assertEqual(addr.narrative, "campaign")
        self.assertEqual(addr.key_path, ("event_1", "scene_2"))
        self.assertEqual(str(addr), "campaign/event_1/scene_2")

    def test_line_single(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1@15")
        self.assertEqual(addr.line, 15)
        self.assertIsNone(addr.line_end)
        self.assertEqual(str(addr), "campaign/event_1@15")

    def test_line_range(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1@15:30")
        self.assertEqual(addr.line, 15)
        self.assertEqual(addr.line_end, 30)
        self.assertEqual(str(addr), "campaign/event_1@15:30")

    def test_operator_with_id(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1#section:aside")
        self.assertEqual(addr.operator, "section")
        self.assertEqual(addr.op_id, "aside")
        self.assertEqual(str(addr), "campaign/event_1#section:aside")

    def test_operator_without_id(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1#write")
        self.assertEqual(addr.operator, "write")
        self.assertIsNone(addr.op_id)
        self.assertEqual(str(addr), "campaign/event_1#write")

    def test_full_spec(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1@5:10#edit:fix1")
        self.assertEqual(addr.narrative, "campaign")
        self.assertEqual(addr.key_path, ("event_1",))
        self.assertEqual(addr.line, 5)
        self.assertEqual(addr.line_end, 10)
        self.assertEqual(addr.operator, "edit")
        self.assertEqual(addr.op_id, "fix1")
        self.assertEqual(str(addr), "campaign/event_1@5:10#edit:fix1")

    def test_relative_with_line(self) -> None:
        addr = NarrativeAddress.parse("/event_1@15")
        self.assertIsNone(addr.narrative)
        self.assertEqual(addr.key_path, ("event_1",))
        self.assertEqual(addr.line, 15)
        self.assertEqual(str(addr), "/event_1@15")


class TestNarrativeAddressRoundTrip(unittest.TestCase):
    def test_roundtrip_full(self) -> None:
        s = "campaign/event_1/scene_2@5:10#edit:fix1"
        addr = NarrativeAddress.parse(s)
        self.assertEqual(str(addr), s)

    def test_roundtrip_cursor(self) -> None:
        addr = NarrativeAddress.parse("/@cursor")
        self.assertEqual(str(addr), "/@cursor")

    def test_roundtrip_relative(self) -> None:
        addr = NarrativeAddress.parse("/event_1@15#write")
        self.assertEqual(str(addr), "/event_1@15#write")


class TestNarrativeAddressNodeOnly(unittest.TestCase):
    def test_strips_line_and_operator(self) -> None:
        addr = NarrativeAddress.parse("campaign/event_1@15:30#section:aside")
        node_only = addr.node_only()
        self.assertEqual(node_only.narrative, "campaign")
        self.assertEqual(node_only.key_path, ("event_1",))
        self.assertIsNone(node_only.line)
        self.assertIsNone(node_only.line_end)
        self.assertIsNone(node_only.operator)
        self.assertIsNone(node_only.op_id)
        self.assertEqual(str(node_only), "campaign/event_1")

    def test_cursor_unchanged(self) -> None:
        addr = NarrativeAddress.parse("/@cursor")
        node_only = addr.node_only()
        self.assertTrue(node_only.cursor)


class TestNarrativeAddressWithNarrative(unittest.TestCase):
    def test_fills_none(self) -> None:
        addr = NarrativeAddress.parse("/event_1")
        filled = addr.with_narrative("campaign")
        self.assertEqual(filled.narrative, "campaign")
        self.assertEqual(filled.key_path, ("event_1",))
        self.assertEqual(str(filled), "campaign/event_1")

    def test_replaces_existing(self) -> None:
        addr = NarrativeAddress.parse("old/event_1")
        filled = addr.with_narrative("campaign")
        self.assertEqual(filled.narrative, "campaign")


class TestNarrativeAddressFromFile(unittest.TestCase):
    def test_root_node(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation("narrative/test/_node.md")
        self.assertEqual(addr.narrative, "test")
        self.assertEqual(addr.key_path, ())

    def test_folder_node(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/event_1/scene_2/_node.md"
        )
        self.assertEqual(addr.narrative, "test")
        self.assertEqual(addr.key_path, ("event_1", "scene_2"))

    def test_leaf_node(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/event_1.md"
        )
        self.assertEqual(addr.narrative, "test")
        self.assertEqual(addr.key_path, ("event_1",))

    def test_with_annotation(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md",
            operator="section",
            op_id="ch1",
        )
        self.assertEqual(addr.operator, "section")
        self.assertEqual(addr.op_id, "ch1")

    def test_with_line(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md",
            operator="write",
            line=15,
        )
        self.assertEqual(addr.line, 15)
        self.assertEqual(addr.operator, "write")

    def test_rejects_non_narrative_path(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            NarrativeAddress.from_file_and_annotation("knowledge/place/nyc.md")
        self.assertIn("narrative", str(ctx.exception))


class TestNarrativeAddressToNode(unittest.TestCase):
    def test_resolves_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(Path(tmp))
            addr = NarrativeAddress(narrative="test", key_path=())
            node = addr.to_node(root)
            self.assertEqual(node.key_path, ())
            self.assertEqual(node.narrative_root, root / "narrative" / "test")

    def test_resolves_nested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(Path(tmp))
            (root / "narrative" / "test" / "event_1").mkdir()
            (root / "narrative" / "test" / "event_1" / "_node.md").write_text("# event_1\n")
            addr = NarrativeAddress(narrative="test", key_path=("event_1",))
            node = addr.to_node(root)
            self.assertEqual(node.key_path, ("event_1",))

    def test_requires_narrative(self) -> None:
        addr = NarrativeAddress(narrative=None, key_path=("event_1",))
        with self.assertRaises(ValueError) as ctx:
            addr.to_node(Path("/tmp"))
        self.assertIn("narrative", str(ctx.exception))


class TestNarrativeNodeToAddress(unittest.TestCase):
    def test_root_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(Path(tmp))
            narrative_dir = root / "narrative" / "test"
            node = NarrativeNode(narrative_root=narrative_dir, key_path=())
            addr = node.to_address()
            self.assertEqual(addr.narrative, "test")
            self.assertEqual(addr.key_path, ())

    def test_nested_node(self) -> None:
        narrative_dir = Path("/narrative/campaign")
        node = NarrativeNode(
            narrative_root=narrative_dir,
            key_path=("event_1", "scene_2"),
        )
        addr = node.to_address()
        self.assertEqual(addr.narrative, "campaign")
        self.assertEqual(addr.key_path, ("event_1", "scene_2"))


class TestNarrativeAddressValidation(unittest.TestCase):
    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            NarrativeAddress.parse("")

    def test_invalid_slug_raises(self) -> None:
        with self.assertRaises(ValueError):
            NarrativeAddress.parse("campaign/event-1!bad")

    def test_invalid_line_raises(self) -> None:
        with self.assertRaises(ValueError):
            NarrativeAddress.parse("campaign@abc")
