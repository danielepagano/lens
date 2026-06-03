"""Tests for summarize → remember workflow step planning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lens.core.context import CrawlResult
from lens.core.project import ProjectSession
from lens.core.workflow_summarize import (
    SummarizeRememberState,
    build_summarize_remember_steps,
    remember_should_run,
)


class TestRememberShouldRun(unittest.TestCase):
    def test_false_without_pins(self) -> None:
        crawl = MagicMock(spec=CrawlResult)
        crawl.pinned_ids = []
        self.assertFalse(remember_should_run(crawl, Path("/tmp")))

    def test_false_when_no_remember_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge" / "person").mkdir(parents=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Amy\n", encoding="utf-8")
            (root / "knowledge" / "tags.toml").write_text(
                '[tags]\nperson.amy = ["fiction"]\n', encoding="utf-8"
            )
            crawl = MagicMock(spec=CrawlResult)
            crawl.pinned_ids = ["person.amy"]
            self.assertFalse(remember_should_run(crawl, root))


class TestRememberStepPlan(unittest.TestCase):
    def test_remember_omitted_from_plan_without_remember_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge" / "person").mkdir(parents=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Amy\n", encoding="utf-8")
            (root / "knowledge" / "tags.toml").write_text(
                '[tags]\nperson.amy = ["fiction"]\n', encoding="utf-8"
            )
            session = ProjectSession(git_root=root, project_root=root)
            crawl = MagicMock(spec=CrawlResult)
            crawl.pinned_ids = ["person.amy"]
            state = SummarizeRememberState(slug="ch", content="section prose here")
            steps = build_summarize_remember_steps(
                state,
                session=session,
                cursor=MagicMock(),
                operator_name="section",
                llm_id=None,
                reasoning=None,
                on_token=None,
                cancel_event=None,
                storage=None,
                system_key="session.summary_system",
                instruction_key="session.summary_instruction_template",
                prepare_crawl=lambda: crawl,
                summarize_empty=True,
            )
            remember = next(s for s in steps if s.id == "remember")
            self.assertFalse(remember.should_run())
