"""Bench lane (B-01–B-07): scenario contract smoke — not scored LLM runs."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCENARIOS = _REPO / "bench" / "scenarios"

BENCH_SCENARIOS: list[tuple[str, bool]] = [
    ("remember_section", True),
    ("section_summary", True),
    ("advance_fronts", True),
    ("play_gm_voice", True),
    ("write_coherence", False),
    ("edit_quality", True),
    ("design_instructions", False),
]


@pytest.mark.parametrize(("name", "has_setup_script"), BENCH_SCENARIOS)
def test_bench_scenario_files_exist(name: str, has_setup_script: bool) -> None:
    md = _SCENARIOS / f"{name}.md"
    assert md.is_file(), f"missing bench scenario {md}"
    if has_setup_script:
        sh = _SCENARIOS / f"{name}_setup.sh"
        assert sh.is_file(), f"missing setup script {sh}"


def test_run_bench_regression_script_exists() -> None:
    script = _REPO / "e2e" / "fixtures" / "run_bench_regression.sh"
    assert script.is_file()
