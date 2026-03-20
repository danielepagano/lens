"""Tests for AdvanceOperator."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.context import CrawlResult
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession
from lens.dnd.operators.advance import (
    AdvanceOperator,
    discover_front_pins,
    generate_advance_id,
    generate_luck_rolls,
    parse_advance_result,
    read_current_day,
)


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(
        f'[project]\nnarrative = "{slug}"\ndatasets = ["dnd"]\n'
    )
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


# ---------------------------------------------------------------------------
# generate_advance_id
# ---------------------------------------------------------------------------


class TestGenerateAdvanceId(unittest.TestCase):
    def test_first_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            result = generate_advance_id(narrative)
            self.assertEqual(result, "advance-day-1")

    def test_monotonic_increment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Simulate existing sub-nodes
            md_dir = narrative.md_path().parent
            (md_dir / "advance-day-1.md").write_text("")
            (md_dir / "advance-day-2.md").write_text("")
            result = generate_advance_id(narrative)
            self.assertEqual(result, "advance-day-3")

    def test_gap_fills_first_available(self) -> None:
        """If advance-day-1 and advance-day-3 exist, next is advance-day-2."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            md_dir = narrative.md_path().parent
            (md_dir / "advance-day-1.md").write_text("")
            (md_dir / "advance-day-3.md").write_text("")
            result = generate_advance_id(narrative)
            self.assertEqual(result, "advance-day-2")


# ---------------------------------------------------------------------------
# parse_advance_result
# ---------------------------------------------------------------------------


class TestParseAdvanceResult(unittest.TestCase):
    def test_full_increment_when_no_block(self) -> None:
        content = "Some narrative text without any advance block."
        self.assertEqual(parse_advance_result(content, 3), 3)

    def test_parse_valid_block(self) -> None:
        content = "Stuff\n```advance\ndays_elapsed: 2\n```\nMore stuff"
        self.assertEqual(parse_advance_result(content, 5), 2)

    def test_clamp_below_one(self) -> None:
        content = "```advance\ndays_elapsed: 0\n```"
        self.assertEqual(parse_advance_result(content, 3), 1)

    def test_clamp_above_increment(self) -> None:
        content = "```advance\ndays_elapsed: 10\n```"
        self.assertEqual(parse_advance_result(content, 3), 3)

    def test_exact_increment(self) -> None:
        content = "```advance\ndays_elapsed: 3\n```"
        self.assertEqual(parse_advance_result(content, 3), 3)

    def test_single_day(self) -> None:
        content = "```advance\ndays_elapsed: 1\n```"
        self.assertEqual(parse_advance_result(content, 1), 1)

    def test_invalid_yaml_returns_default(self) -> None:
        content = "```advance\nnot valid yaml: [[[[\n```"
        self.assertEqual(parse_advance_result(content, 2), 2)

    def test_missing_key_returns_default(self) -> None:
        content = "```advance\nsome_other_key: 5\n```"
        self.assertEqual(parse_advance_result(content, 3), 3)


# ---------------------------------------------------------------------------
# discover_front_pins
# ---------------------------------------------------------------------------


class TestDiscoverFrontPins(unittest.TestCase):
    def test_finds_fronts_with_timeline_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, _ = _make_project(d)
            # Create front objects and tag them
            kb_dir = d / "knowledge"
            front_dir = kb_dir / "front"
            front_dir.mkdir(parents=True)
            (front_dir / "goblins.md").write_text("Goblin threat")
            (front_dir / "drought.md").write_text("Water shortage")
            # Create tags.toml
            (kb_dir / "tags.toml").write_text(
                '[tags]\n"timeline.epic" = ["front.goblins", "front.drought"]\n'
            )
            session = ProjectSession(root, root)
            result = discover_front_pins(
                session.kb,
                ["timeline.epic", "design.front"],
            )
            self.assertEqual(result, ["front.drought+", "front.goblins+"])

    def test_no_fronts_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, _ = _make_project(d)
            session = ProjectSession(root, root)
            result = discover_front_pins(session.kb, ["timeline.epic"])
            self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# generate_luck_rolls
# ---------------------------------------------------------------------------


class TestGenerateLuckRolls(unittest.TestCase):
    def test_correct_keys_and_range(self) -> None:
        front_ids = ["front.goblins", "front.drought"]
        rolls = generate_luck_rolls(front_ids)
        self.assertEqual(set(rolls.keys()), set(front_ids))
        for _fid, (r1, r2) in rolls.items():
            self.assertGreaterEqual(r1, 1)
            self.assertLessEqual(r1, 100)
            self.assertGreaterEqual(r2, 1)
            self.assertLessEqual(r2, 100)

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(generate_luck_rolls([]), {})


# ---------------------------------------------------------------------------
# read_current_day
# ---------------------------------------------------------------------------


class TestReadCurrentDay(unittest.TestCase):
    def test_reads_day_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, _ = _make_project(d)
            kb_dir = d / "knowledge" / "timeline"
            kb_dir.mkdir(parents=True)
            (kb_dir / "epic.md").write_text(
                "Chronicle\n\n- Started: 1st Deepwinter\n- Day: 42\n"
            )
            session = ProjectSession(root, root)
            self.assertEqual(read_current_day(session.kb, "timeline.epic"), 42)

    def test_missing_object_returns_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, _ = _make_project(d)
            session = ProjectSession(root, root)
            self.assertEqual(read_current_day(session.kb, "timeline.missing"), 1)


# ---------------------------------------------------------------------------
# check_requirements
# ---------------------------------------------------------------------------


class TestCheckRequirements(unittest.TestCase):
    def test_missing_design_front(self) -> None:
        cr = CrawlResult(
            knowledge=[],
            pinned_ids=["timeline.epic"],
            previous_summaries=[],
            current_content="",
        )
        with self.assertRaises(OperatorError) as ctx:
            AdvanceOperator.check_requirements(cr)
        self.assertIn("design.front", str(ctx.exception))

    def test_missing_timeline(self) -> None:
        cr = CrawlResult(
            knowledge=[],
            pinned_ids=["design.front"],
            previous_summaries=[],
            current_content="",
        )
        with self.assertRaises(OperatorError) as ctx:
            AdvanceOperator.check_requirements(cr)
        self.assertIn("timeline", str(ctx.exception))

    def test_passes_with_both(self) -> None:
        cr = CrawlResult(
            knowledge=[],
            pinned_ids=["design.front", "timeline.epic"],
            previous_summaries=[],
            current_content="",
        )
        # Should not raise
        AdvanceOperator.check_requirements(cr)


# ---------------------------------------------------------------------------
# build_instruction
# ---------------------------------------------------------------------------


class TestBuildInstruction(unittest.TestCase):
    def test_includes_increment_and_rolls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = _make_project(d)
            from lens.core.storage import Storage
            storage = Storage(root)
            op = AdvanceOperator(storage, narrative)
            params: dict[str, Any] = {
                "increment": 3,
                "current_day": 10,
                "luck_rolls": {"front.goblins": (42, 77)},
            }
            instruction = op.build_instruction(params)
            self.assertIn("3 day(s)", instruction)
            self.assertIn("10", instruction)
            self.assertIn("front.goblins", instruction)
            self.assertIn("42", instruction)
            self.assertIn("77", instruction)

    def test_no_fronts_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = _make_project(d)
            from lens.core.storage import Storage
            storage = Storage(root)
            op = AdvanceOperator(storage, narrative)
            params: dict[str, Any] = {"increment": 1, "current_day": 1, "luck_rolls": {}}
            instruction = op.build_instruction(params)
            self.assertIn("no fronts", instruction)


if __name__ == "__main__":
    unittest.main()
