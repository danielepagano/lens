"""CLI+git regression cases (AC-*) from the 1524eaf0→HEAD plan."""

from __future__ import annotations

import contextlib
import io
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lens.core.auto_compress import read_cursor_auto_compress_state
from lens.core.commands.rollback import execute_rollback
from lens.core.narrative import NarrativeNode
from lens.core.operators.section import SectionOperator
from lens.core.operators.write import WriteOperator
from lens.core.storage import Storage
from lens.core.test.llm_run_mock import mock_run_llm
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import _quiet_async
from lens.rpg.operators.play import PlayOperator
from lens.testing.regression_fixtures import (
    setup_advance_minimal,
    setup_auto_compress_disabled_node,
    setup_auto_compress_low_threshold,
    setup_remember_section,
    setup_rpg_play_pins,
)


def _git_status_porcelain(project: Path) -> str:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout


@pytest.fixture
def fake_llm() -> FakeLLMServer:
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def tmp_project(tmp_path: Path, fake_llm: FakeLLMServer) -> Path:
    return tmp_path


class TestRegressionCliAutoCompress:
    """AC-01 – AC-03: auto-compress eligibility and disable."""

    def test_ac01_write_leaves_unstaged_pending(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        session = setup_auto_compress_low_threshold(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None

        state = read_cursor_auto_compress_state(session, narrative)
        assert state.compress_on
        assert state.trigger is not None, "fixture seed should warrant auto-compress"

        async def _text(*_a: object, **_k: object) -> str:
            return "Generated beat.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            with patch(
                "lens.core.auto_compress.run_compress",
                new_callable=AsyncMock,
                return_value=None,
            ):
                _quiet_async(
                    WriteOperator.run_inline(
                        session=session,
                        narrative=narrative,
                        prompt="beat",
                        pins=[],
                        unpins=[],
                        llm_id="mock",
                        retry=False,
                    )
                )

        assert Storage(tmp_project).has_pending()
        assert _git_status_porcelain(tmp_project).strip() != ""

    def test_ac03_node_fm_disables_auto_compress(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        session = setup_auto_compress_disabled_node(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None
        state = read_cursor_auto_compress_state(session, narrative)
        assert not state.compress_on


class TestRegressionCliRememberSection:
    """AC-05: section end runs summarize path (remember optional)."""

    def test_ac05_section_end_writes_parent_summary(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        session = setup_remember_section(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None
        async def _summary(*_a: object, **_k: object) -> str:
            return "Summary of Rex and lime tea.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_summary)):
            with patch(
                "lens.core.operators.session.apply_remember_patches",
                new_callable=AsyncMock,
                return_value="",
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    _quiet_async(
                        SectionOperator.run_end(
                            session=session,
                            narrative=narrative,
                            llm_id="mock",
                            reasoning=None,
                            summary_guidance=None,
                        )
                    )

        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=(),
        )
        parent_text = parent.md_path().read_text(encoding="utf-8")
        assert "### Integration Summary" in parent_text
        assert "[/section:remember-smoke]" in parent_text


class TestRegressionCliTransactions:
    """AC-07: rollback clears pending preview."""

    def test_ac07_rollback_clears_pending(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        session = setup_auto_compress_low_threshold(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None

        async def _text(*_a: object, **_k: object) -> str:
            return "To discard.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            _quiet_async(
                WriteOperator.run_inline(
                    session=session,
                    narrative=narrative,
                    prompt="x",
                    pins=[],
                    unpins=[],
                    llm_id="mock",
                    retry=False,
                )
            )
        assert Storage(tmp_project).has_pending()
        execute_rollback(session)
        assert not Storage(tmp_project).has_pending()
        assert _git_status_porcelain(tmp_project).strip() == ""


class TestRegressionCliPreTransforms:
    """AC-11, AC-13: @var and @roll expansion on persist."""

    def test_ac11_var_expansion_in_write(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        from lens.testing.project import setup_test_project

        session = setup_test_project(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        cursor.md_path().write_text(
            "[\n    vars:\n        foo: bar\n]: #\n\n# test\n",
            encoding="utf-8",
        )
        Storage(tmp_project).stage_all()
        subprocess.run(["git", "add", "-A"], cwd=tmp_project, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "vars"],
            cwd=tmp_project,
            check=True,
            capture_output=True,
        )

        async def _text(*_a: object, **_k: object) -> str:
            return "Done.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            _quiet_async(
                WriteOperator.run_inline(
                    session=session,
                    narrative=narrative,
                    prompt="see @foo",
                    pins=[],
                    unpins=[],
                    llm_id="mock",
                    retry=False,
                )
            )

        text = cursor.md_path().read_text(encoding="utf-8")
        assert "bar" in text
        assert "@foo" not in text.split("[write")[0]

    def test_ac13_roll_expansion_in_play(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        session = setup_rpg_play_pins(tmp_project, fake_llm.base_url)
        narrative = session.active_narrative
        assert narrative is not None

        async def _no_gm(*_a: object, **_k: object) -> str:
            raise AssertionError("play should not call the LLM for a player-only line")

        with patch("lens.core.operator.run_llm", mock_run_llm(_no_gm)):
            _quiet_async(
                PlayOperator.run_session(
                    session=session,
                    narrative=narrative,
                    prompt="@roll 1d6",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )

        play_keys = [k for k in narrative.child_keys() if k.startswith("play")]
        assert play_keys, list(narrative.child_keys())
        text = narrative.child_node(play_keys[0]).md_path().read_text(encoding="utf-8")
        assert "@roll" not in text
        assert "> [Player]" in text


class TestRegressionCliAdvanceFixture:
    """AC-16: advance_minimal fixture seeds timeline KB."""

    def test_advance_minimal_fixture_kb(self, tmp_project: Path, fake_llm: FakeLLMServer) -> None:
        setup_advance_minimal(tmp_project, fake_llm.base_url)
        timeline = tmp_project / "knowledge" / "timeline" / "vale.md"
        assert timeline.is_file()
        assert "Thornvale" in timeline.read_text(encoding="utf-8")
