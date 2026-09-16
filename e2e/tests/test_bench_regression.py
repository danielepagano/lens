"""Bench lane (B-01–B-07): scenario contract smoke — not scored LLM runs."""

from __future__ import annotations

import sys
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
    ("model_gate", True),
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


def test_model_gate_probes_parse() -> None:
    """`model_gate.py` reads its probes out of the scenario, so the format is a contract.

    Nothing else asserts on it: a probe whose fence is mislabelled simply stops
    being swept, and the tool reports on the probes that are left without saying
    the others went missing. That is a silent shrinking of a disqualifier gate.
    """
    sys.path.insert(0, str(_REPO / "bench" / "tools"))
    from model_gate import parse_probes  # noqa: PLC0415

    probes = parse_probes(_SCENARIOS / "model_gate.md")
    ids = [p.probe_id for p in probes]
    assert ids == [
        "villain_commitment",
        "npc_betrayal",
        "content_violence",
        "content_intimacy",
        "content_cruelty",
    ], ids
    for probe in probes:
        assert probe.scene.strip(), f"{probe.probe_id}: empty scene block"
        assert "kb_pin:" in probe.scene, f"{probe.probe_id}: scene pins nothing"
        assert probe.command.startswith("lens play "), probe.command
        # Arm 1 needs --pass; the rest are --retry, which implies it and rejects it.
        assert (
            "--pass" in probe.command
        ), f"{probe.probe_id}: first arm would not generate"
