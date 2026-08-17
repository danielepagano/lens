"""Tests for AdvanceOperator."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.context import CrawlResult
from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.narrative import NarrativeNode
from lens.core.exceptions import ValidationError
from lens.core.project import ProjectSession
from lens.core.test.llm_run_mock import run_llm_from_text
from lens.rpg.operators.advance import (
    AdvanceOperator,
    find_advance_anchor,
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
        f'[project]\nnarrative = "{slug}"\ndatasets = ["rpg"]\n'
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


def _register_advance_child(parent: NarrativeNode, advance_id: str) -> None:
    """Register an advance sub-node on *parent* (annotation + backing file)."""
    parent_md = parent.md_path()
    parent_md.write_text(
        parent_md.read_text(encoding="utf-8").rstrip() + f"\n[advance:{advance_id}]: #\n",
        encoding="utf-8",
    )
    child_dir = parent.narrative_root / advance_id
    child_dir.mkdir(exist_ok=True)
    (child_dir / "_node.md").write_text("advance\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# generate_advance_id
# ---------------------------------------------------------------------------


class TestGenerateAdvanceId(unittest.TestCase):
    def test_uses_current_day_as_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            result = generate_advance_id(narrative, 42)
            self.assertEqual(result, "advance-day-42")

    def test_day_one_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            result = generate_advance_id(narrative, 1)
            self.assertEqual(result, "advance-day-1")

    def test_raises_on_duplicate_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            _register_advance_child(narrative, "advance-day-7")
            with self.assertRaises(ValidationError):
                generate_advance_id(narrative, 7)


# ---------------------------------------------------------------------------
# parse_advance_result
# ---------------------------------------------------------------------------


class TestParseAdvanceResult(unittest.TestCase):
    def test_full_increment_when_no_block(self) -> None:
        content = "Some narrative text without any advance block."
        days, summary = parse_advance_result(content, 3)
        self.assertEqual(days, 3)
        self.assertIn("3", summary)

    def test_parse_valid_block(self) -> None:
        content = "Stuff\n```advance\ndays_elapsed: 2\n```\nMore stuff"
        days, _ = parse_advance_result(content, 5)
        self.assertEqual(days, 2)

    def test_clamp_below_one(self) -> None:
        content = "```advance\ndays_elapsed: 0\n```"
        days, _ = parse_advance_result(content, 3)
        self.assertEqual(days, 1)

    def test_clamp_above_increment(self) -> None:
        content = "```advance\ndays_elapsed: 10\n```"
        days, _ = parse_advance_result(content, 3)
        self.assertEqual(days, 3)

    def test_exact_increment(self) -> None:
        content = "```advance\ndays_elapsed: 3\n```"
        days, _ = parse_advance_result(content, 3)
        self.assertEqual(days, 3)

    def test_single_day(self) -> None:
        content = "```advance\ndays_elapsed: 1\n```"
        days, _ = parse_advance_result(content, 1)
        self.assertEqual(days, 1)

    def test_invalid_yaml_returns_default(self) -> None:
        content = "```advance\nnot valid yaml: [[[[\n```"
        days, summary = parse_advance_result(content, 2)
        self.assertEqual(days, 2)
        self.assertIn("2", summary)

    def test_missing_key_returns_default(self) -> None:
        content = "```advance\nsome_other_key: 5\n```"
        days, summary = parse_advance_result(content, 3)
        self.assertEqual(days, 3)
        self.assertIn("3", summary)

    def test_summary_extracted(self) -> None:
        content = "```advance\nsummary: Two days pass quietly.\n```"
        days, summary = parse_advance_result(content, 3)
        self.assertEqual(days, 3)
        self.assertEqual(summary, "Two days pass quietly.")

    def test_summary_and_days_elapsed(self) -> None:
        content = "```advance\ndays_elapsed: 2\nsummary: Orcs attack on day two.\n```"
        days, summary = parse_advance_result(content, 5)
        self.assertEqual(days, 2)
        self.assertEqual(summary, "Orcs attack on day two.")

    def test_multiline_summary(self) -> None:
        content = "```advance\nsummary: |\n  Day one is calm.\n  Day two brings rain.\n```"
        days, summary = parse_advance_result(content, 3)
        self.assertEqual(days, 3)
        self.assertIn("Day one is calm.", summary or "")
        self.assertIn("Day two brings rain.", summary or "")


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

    def test_missing_object_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, _ = _make_project(d)
            session = ProjectSession(root, root)
            with self.assertRaises(ValidationError):
                read_current_day(session.kb, "timeline.missing")


# ---------------------------------------------------------------------------
# check_requirements
# ---------------------------------------------------------------------------


class TestCheckRequirements(unittest.TestCase):
    def test_timeline_only_passes_without_operator_module(self) -> None:
        cr = CrawlResult.from_text_fields(
            knowledge=[],
            pinned_ids=["timeline.epic"],
            previous_summaries=[],
            current_content="",
        )
        AdvanceOperator.check_requirements(cr)

    def test_missing_timeline(self) -> None:
        cr = CrawlResult.from_text_fields(
            knowledge=[],
            pinned_ids=["rules.advance"],
            previous_summaries=[],
            current_content="",
        )
        with self.assertRaises(ValidationError) as ctx:
            AdvanceOperator.check_requirements(cr)
        self.assertIn("timeline", str(ctx.exception))

    def test_passes_with_timeline_and_optional_operator_module(self) -> None:
        cr = CrawlResult.from_text_fields(
            knowledge=[],
            pinned_ids=["rules.advance", "timeline.epic"],
            previous_summaries=[],
            current_content="",
        )
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


# ---------------------------------------------------------------------------
# run_advance — summary written to cursor node
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run *coro* in a dedicated thread to avoid event-loop conflicts."""
    result: list[Any] = []
    exc: list[BaseException] = []

    def _go() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as e:  # noqa: BLE001
            exc.append(e)

    t = threading.Thread(target=_go)
    t.start()
    t.join()
    if exc:
        raise exc[0]
    return result[0]


class TestRunAdvanceSummary(unittest.TestCase):
    """Fresh advance writes LLM output to the sub-node; --end applies summary + close on parent."""

    def _make_rpg_project(self, d: Path) -> tuple[Path, NarrativeNode]:
        root, narrative = _make_project(d, slug="campaign")
        # Timeline KB object with a Day counter
        timeline_dir = d / "knowledge" / "timeline"
        timeline_dir.mkdir(parents=True)
        (timeline_dir / "epic.md").write_text("The Epic Timeline\n\n- Day: 1\n")
        # Empty tags index (no fronts to discover is fine)
        (d / "knowledge" / "tags.toml").write_text("[tags]\n")
        subprocess.run(["git", "add", "-A"], cwd=d, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "kb: timeline"], cwd=d, capture_output=True, check=True
        )
        return root, narrative

    def _mock_run_llm(self, response_text: str) -> Any:
        return run_llm_from_text(response_text)

    def test_summary_written_between_advance_tags(self) -> None:
        SUMMARY = "Three days pass without incident on the road."
        LLM_RESPONSE = f"```advance\ndays_elapsed: 1\nsummary: {SUMMARY}\n```"

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = self._make_rpg_project(d)
            session = ProjectSession(root, root)

            with patch(
                "lens.rpg.operators.advance.run_llm",
                self._mock_run_llm(LLM_RESPONSE),
            ):
                _run_async(
                    AdvanceOperator.run_advance(
                        session=session,
                        narrative=narrative,
                        increment=1,
                        pins=["timeline.epic"],
                        unpins=[],
                    )
                )

            parent_md = narrative.md_path()
            parent_before_end = parent_md.read_text(encoding="utf-8")
            self.assertIn("[advance:", parent_before_end)
            self.assertNotIn("[/advance:", parent_before_end)

            child_md = narrative.find_cursor().md_path()
            self.assertIn(SUMMARY, child_md.read_text(encoding="utf-8"))

            _run_async(
                AdvanceOperator.run_advance(
                    session=session,
                    narrative=narrative,
                    increment=1,
                    pins=[],
                    unpins=[],
                    end=True,
                )
            )

            content = parent_md.read_text(encoding="utf-8")
            open_pos = content.find("[advance:")
            close_pos = content.find("[/advance:")
            summary_pos = content.find(SUMMARY)
            self.assertGreater(open_pos, -1, "advance open tag missing")
            self.assertGreater(close_pos, open_pos, "advance close tag missing")
            self.assertGreater(summary_pos, open_pos, "summary must be after open tag")
            self.assertLess(summary_pos, close_pos, "summary must be before close tag")

            timeline_text = (d / "knowledge" / "timeline" / "epic.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("- Day: 2", timeline_text)

    def test_default_message_when_no_advance_block(self) -> None:
        """When LLM emits no advance block, end uses the default day message."""
        LLM_RESPONSE = "All fronts are quiet, nothing notable happened."

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = self._make_rpg_project(d)
            session = ProjectSession(root, root)

            with patch(
                "lens.rpg.operators.advance.run_llm",
                self._mock_run_llm(LLM_RESPONSE),
            ):
                _run_async(
                    AdvanceOperator.run_advance(
                        session=session,
                        narrative=narrative,
                        increment=3,
                        pins=["timeline.epic"],
                        unpins=[],
                    )
                )

            parent_md = narrative.md_path()
            self.assertNotIn("[/advance:", parent_md.read_text(encoding="utf-8"))

            _run_async(
                AdvanceOperator.run_advance(
                    session=session,
                    narrative=narrative,
                    increment=3,
                    pins=[],
                    unpins=[],
                    end=True,
                )
            )

            content = parent_md.read_text(encoding="utf-8")
            self.assertIn("3", content)
            self.assertIn("[advance:", content)
            self.assertIn("[/advance:", content)

            timeline_text = (d / "knowledge" / "timeline" / "epic.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("- Day: 4", timeline_text)

    def test_interrupt_on_fresh_discards_partial_output(self) -> None:
        PARTIAL = "Partial advance output before cancel."

        async def _interrupted_partial(*_args: Any, **_kwargs: Any) -> GenerationArtifacts:
            return GenerationArtifacts(
                segments=[GenerationSegment("prose", PARTIAL)],
                interrupted=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = self._make_rpg_project(d)
            session = ProjectSession(root, root)

            with patch(
                "lens.rpg.operators.advance.run_llm",
                _interrupted_partial,
            ):
                _run_async(
                    AdvanceOperator.run_advance(
                        session=session,
                        narrative=narrative,
                        increment=1,
                        pins=["timeline.epic"],
                        unpins=[],
                    )
                )

            child_md = narrative.find_cursor().md_path()
            self.assertNotIn(PARTIAL, child_md.read_text(encoding="utf-8"))
            self.assertNotIn("[advance:", child_md.read_text(encoding="utf-8"))

    def test_interrupt_on_retry_restores_snapshot(self) -> None:
        LLM_RESPONSE = "```advance\ndays_elapsed: 1\nsummary: First pass.\n```"
        FIRST_PASS = "First pass."

        async def _interrupted_empty(*_args: Any, **_kwargs: Any) -> GenerationArtifacts:
            return GenerationArtifacts(interrupted=True)

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            root, narrative = self._make_rpg_project(d)
            session = ProjectSession(root, root)

            with patch(
                "lens.rpg.operators.advance.run_llm",
                self._mock_run_llm(LLM_RESPONSE),
            ):
                _run_async(
                    AdvanceOperator.run_advance(
                        session=session,
                        narrative=narrative,
                        increment=1,
                        pins=["timeline.epic"],
                        unpins=[],
                    )
                )

            child = narrative.find_cursor()
            child_md = child.md_path()
            before_retry = child_md.read_text(encoding="utf-8")
            self.assertIn(FIRST_PASS, before_retry)

            with patch(
                "lens.rpg.operators.advance.run_llm",
                _interrupted_empty,
            ):
                _run_async(
                    AdvanceOperator.run_advance(
                        session=session,
                        narrative=narrative,
                        increment=1,
                        pins=[],
                        unpins=[],
                        retry=True,
                    )
                )

            self.assertEqual(child_md.read_text(encoding="utf-8"), before_retry)


# ---------------------------------------------------------------------------
# find_advance_anchor
# ---------------------------------------------------------------------------


def _write_completed_advance(
    parent_node: NarrativeNode,
    advance_id: str,
    timeline_id: str,
    current_day: int,
    increment: int,
    days_elapsed: int | None = None,
) -> None:
    """Simulate a completed advance session on parent_node.

    Writes the open/close tags on the parent and creates the sub-node
    with an advance block containing the result.
    """
    actual_days = days_elapsed if days_elapsed is not None else increment
    # Build annotation params YAML
    params_yaml = (
        f"  increment: {increment}\n"
        f"  current_day: {current_day}\n"
        f"  timeline: {timeline_id}\n"
        f"  luck_rolls: {{}}\n"
    )
    open_tag = f"[advance:{advance_id}\n{params_yaml}]: #"
    close_tag = f"[/advance:{advance_id}]: #"

    summary = f"{actual_days} day(s) have passed."
    parent_md = parent_node.md_path()
    existing = parent_md.read_text(encoding="utf-8")
    parent_md.write_text(
        existing + f"\n{open_tag}\n\n{summary}\n\n{close_tag}\n"
    )

    # Create sub-node with advance block
    child_dir = parent_node.narrative_root / "/".join(parent_node.key_path) / advance_id if parent_node.key_path else parent_node.narrative_root / advance_id
    child_dir.mkdir(parents=True, exist_ok=True)
    advance_block = f"```advance\ndays_elapsed: {actual_days}\nsummary: {summary}\n```"
    (child_dir / "_node.md").write_text(
        f"[kb_pin: [{timeline_id}]]: #\n\n{advance_block}\n"
    )


class TestFindAdvanceAnchor(unittest.TestCase):
    def test_no_prior_advance_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            result = find_advance_anchor(narrative, "timeline.epic", 1)
            self.assertIsNone(result)

    def test_finds_anchor_on_same_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Simulate a completed advance: started at day 1, elapsed 1, so now day 2
            _write_completed_advance(
                narrative, "advance-day-1", "timeline.epic",
                current_day=1, increment=1,
            )
            result = find_advance_anchor(narrative, "timeline.epic", 2)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.advance_id, "advance-day-1")
            self.assertEqual(result.anchor.node.key_path, narrative.key_path)

    def test_validation_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Advance started at day 1, elapsed 1 → timeline should be at 2
            # But we claim current_day=5 (timeline was edited)
            _write_completed_advance(
                narrative, "advance-day-1", "timeline.epic",
                current_day=1, increment=1,
            )
            with self.assertRaises(ValidationError) as ctx:
                find_advance_anchor(narrative, "timeline.epic", 5)
            self.assertIn("validation failed", str(ctx.exception))

    def test_skips_wrong_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Advance for a DIFFERENT timeline
            _write_completed_advance(
                narrative, "advance-day-1", "timeline.other",
                current_day=1, increment=1,
            )
            # Search for timeline.epic → should not find it
            result = find_advance_anchor(narrative, "timeline.epic", 1)
            self.assertIsNone(result)

    def test_skips_advance_without_timeline_param(self) -> None:
        """Old advance annotations without a timeline param are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Write an advance annotation WITHOUT timeline param (legacy format)
            params_yaml = "  increment: 1\n  current_day: 1\n  luck_rolls: {}\n"
            open_tag = f"[advance:advance-day-1\n{params_yaml}]: #"
            close_tag = "[/advance:advance-day-1]: #"
            parent_md = narrative.md_path()
            existing = parent_md.read_text(encoding="utf-8")
            parent_md.write_text(existing + f"\n{open_tag}\n\nSummary\n\n{close_tag}\n")
            # Create minimal sub-node
            child_dir = narrative.narrative_root / "advance-day-1"
            child_dir.mkdir()
            (child_dir / "_node.md").write_text("Legacy advance\n")

            result = find_advance_anchor(narrative, "timeline.epic", 1)
            self.assertIsNone(result)

    def test_finds_anchor_on_ancestor_node(self) -> None:
        """Anchor on root, cursor deeper in tree."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            _write_completed_advance(
                narrative, "advance-day-1", "timeline.epic",
                current_day=1, increment=1,
            )
            # Create a child node (simulating the cursor being deeper)
            ch1_dir = narrative.narrative_root / "ch1"
            ch1_dir.mkdir()
            (ch1_dir / "_node.md").write_text("Chapter content\n")
            parent_md = narrative.md_path()
            parent_md.write_text(
                parent_md.read_text(encoding="utf-8").rstrip() + "\n[section:ch1]: #\n",
                encoding="utf-8",
            )
            child = NarrativeNode(
                narrative_root=narrative.narrative_root, key_path=("ch1",)
            )
            result = find_advance_anchor(child, "timeline.epic", 2)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.advance_id, "advance-day-1")
            self.assertEqual(result.anchor.node.key_path, ())  # root

    def test_interrupted_advance_validates_correctly(self) -> None:
        """An interrupted advance (days_elapsed < increment) validates correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _, narrative = _make_project(d)
            # Advance requested 3 days but was interrupted after 2
            _write_completed_advance(
                narrative, "advance-day-1", "timeline.epic",
                current_day=5, increment=3, days_elapsed=2,
            )
            # Timeline is now at 5+2=7
            result = find_advance_anchor(narrative, "timeline.epic", 7)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.advance_id, "advance-day-1")


if __name__ == "__main__":
    unittest.main()
