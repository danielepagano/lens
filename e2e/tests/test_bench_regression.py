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
    ("model_rank", True),
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


def test_model_rank_beats_parse() -> None:
    """`model_rank.py` reads its beat sequence out of the scenario, in file order.

    Same contract as the gate's probes and the same silent failure mode: a
    mislabelled fence drops a beat out of the sweep, and the tool reports on
    what is left without saying anything went missing. Here it is worse than a
    shrinking gate — the whole point of the sequence is that the late beats are
    where stamina fails, so losing one silently shortens the only part that
    measures anything.
    """
    sys.path.insert(0, str(_REPO / "bench" / "tools"))
    from model_rank import parse_beats  # noqa: PLC0415

    beats = parse_beats(_SCENARIOS / "model_rank.md")
    assert [b.beat_id for b in beats] == [
        "arrival",
        "send_sable_off",
        "satchel_first",
        "the_bluff",
        "who_told_him",
        "the_poker",
        "out",
        "flat_statement",
        "silence",
        "back_in_the_chair",
    ]
    for beat in beats:
        assert beat.command.startswith("lens play "), beat.command
        assert "--pass" in beat.command, f"{beat.beat_id}: would not generate"
        # Every beat in a sequence generates fresh. `--retry` would re-render the
        # previous beat instead of playing the next one, and `--slug` belongs to
        # the tool, which gives every arm the same session name so the banked
        # play-throughs line up.
        assert "--retry" not in beat.command, f"{beat.beat_id}: re-renders"
        assert "--slug" not in beat.command, f"{beat.beat_id}: owns the session name"
        assert "--llm" not in beat.command, f"{beat.beat_id}: pins the arm"


def test_model_rank_novelty_catches_a_reciter() -> None:
    """The degeneration signal is checked against an answer known in advance.

    Recorded verdicts drift, and in #138 several cited evidence quotes turned
    out to be absent from the data they claimed to come from. So the one number
    this tool contributes gets a case whose answer is not a matter of reading:
    a beat that repeats its predecessor verbatim is 0% novel, and a beat that
    shares nothing with it is 100%.
    """
    sys.path.insert(0, str(_REPO / "bench" / "tools"))
    from model_rank import Beat, measure_arm  # noqa: PLC0415

    said = "The ash never settles in the lower yard and Vetch keeps his hands still."
    other = "Sable laughs too loudly and puts both hands on your shoulders at the gate."
    node = "".join(
        f"> [Player] line {i}\n\n[play\n    llm_id: x\n]: #\n\n{body}\n\n[/play]: #\n\n"
        for i, body in enumerate((said, said, other), start=1)
    )
    beats = [Beat(f"b{i}", "lens play x --pass") for i in range(1, 4)]

    arm = measure_arm("reciter", node, beats, n=5)
    assert [b.words for b in arm.beats] == [14, 14, 14]
    assert arm.beats[0].novel == 1.0
    assert arm.beats[1].novel == 0.0, "a verbatim repeat must read as no novelty"
    assert arm.beats[2].novel == 1.0
