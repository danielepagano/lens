"""Prompt lab: what a prompt change actually does to an assembled context.

Editing a system prompt, a ``design.*`` module, a ``rules.*`` booklet or a
``_template`` is editing an LLM prompt, and the thing that matters is not the
file — it is the **assembled context** the operator ends up sending.  Reading
the diff cannot tell you that a module now costs 800 more tokens, that a
booklet stopped being reachable, or that a rules companion quietly stopped
firing.  This builds a realistic project, drives the real operators, and
reports the composition of every prompt with ``lens explain``::

    poe prompt-lab                       # print every scenario
    poe prompt-lab -- --out /tmp/before  # save a baseline
    …edit prompts / KB…
    poe prompt-lab -- --baseline /tmp/before   # what changed, and by how much

Everything runs through the CLI as a subprocess, on purpose.  ``KnowledgeStore``
caches its tag index per project, so writing KB objects and then crawling in the
same process can read stale tags and silently show a ``+`` expansion resolving
to nothing.  A subprocess always reads the world as a user would.

No model is called for the report itself: ``lens explain`` assembles the prompt
and measures it instead of generating.  A fake LLM is used only to open the
sessions the scenarios need.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

_LENS = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

DEFAULT_DATASETS = ["rpg", "lens-dnd"]


# ---------------------------------------------------------------------------
# Fixture: a small but realistic campaign
# ---------------------------------------------------------------------------

KB_FIXTURES: dict[str, tuple[str, list[str]]] = {
    "pc.kira": (
        "Kira Vance\n\n"
        "- Appearance: lean half-elf scout, mud-grey cloak, moves like she is already leaving.\n"
        "- Context: hunting the caravan raiders who killed her mentor.\n"
        "- How they solve problems: scouts first, talks second, shoots last.\n",
        ["level:3", "faction.wardens"],
    ),
    "faction.wardens": (
        "The Ashfall Wardens\n\n"
        "- Who they are: a thinning road-guard company, paid in salt and promises.\n"
        "- How they operate: patrol in pairs, never chase past the mile-stones.\n",
        [],
    ),
    "timeline.epic": (
        "Name: The Ashfall Road\n\n- Started: 3rd of Deepwinter\n- Day: 12\n",
        ["front.raiders"],
    ),
    "front.raiders": (
        "Caravan raiders on the Ashfall Road\n\n"
        "- Problem: a raider band is taxing every caravan out of Bellmoor.\n"
        "- Stakes if ignored: the road closes and Bellmoor starves by spring.\n"
        "- Known to PCs: they think it is ordinary banditry.\n"
        "- Phases: caravans taxed -> the toll road closes -> Bellmoor rations.\n",
        [],
    ),
    "location.bellmoor-bridge": (
        "Bellmoor Bridge\n\n"
        "- Type of location: stone toll bridge over the Ash.\n"
        "- Sensory feel: wet rope, river noise, tar smoke from the toll hut.\n"
        "- Why it matters: the only crossing that stays open in winter.\n",
        [],
    ),
    "encounter.bridge-ambush": (
        "Bridge Ambush\n\n## Situation\n\n"
        "- **Situation**: raiders hold the far side of Bellmoor Bridge.\n"
        "- **Stakes**: the toll-keeper dies if the fight runs long.\n"
        "- **Initial positions**: party at the near abutment, 40 ft of open span.\n"
        "- **Scene rules**: Slick planks: Difficult Terrain. Crossing at a run is "
        "DC 10 Acrobatics or fall Prone.\n"
        "- **Triggers**: the captain's whistle brings 2 more raiders on round 3.\n"
        "- **Resolution**: raiders break at half strength; the captain covers them.\n\n"
        "## Running non-PC characters\n\nThe captain targets whoever heals first.\n\n"
        "## Prep and reference\n\n- 4x KB['stat.bandit']\n- 1x KB['stat.bandit-captain']\n",
        [
            "location.bellmoor-bridge",
            "front.raiders",
            "stat.bandit",
            "stat.bandit-captain",
            "rules.combat",
        ],
    ),
}

ROOT_PINS = ["pc.kira", "timeline.epic+"]


@dataclass(frozen=True)
class Scenario:
    """One cursor + operator pair to assemble and measure."""

    name: str
    operator: str
    prompt: str
    #: extra pins applied to the narrative root before the run
    pins: list[str] = field(default_factory=lambda: [])
    #: design/play module keys (``--module``, repeatable)
    modules: list[str] = field(default_factory=lambda: [])
    #: run this operator first so the cursor sits in a real session sub-node
    open_session: bool = True


SCENARIOS: list[Scenario] = [
    Scenario("play-open-road", "play", "Kira scouts the road ahead."),
    Scenario(
        "play-encounter",
        "play",
        "Kira steps onto the bridge.",
        pins=["encounter.bridge-ambush+"],
    ),
    Scenario("design-no-module", "design", "Something is wrong in Bellmoor."),
    Scenario(
        "design-encounter", "design", "Build the bridge ambush", modules=["encounter"]
    ),
    Scenario("design-front", "design", "The raiders need a next phase", modules=["front"]),
    Scenario("design-npc", "design", "The toll-keeper", modules=["npc"]),
    Scenario(
        "design-encounter-tracker",
        "design",
        "The ambush and a tracker for it",
        modules=["encounter", "tracker"],
    ),
]


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def lens(*args: str, cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(
        [*_LENS, *args], cwd=cwd, capture_output=True, text=True, timeout=180
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"lens {' '.join(args)} failed ({proc.returncode})\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


def build_project(project_dir: Path, llm_base_url: str, datasets: list[str]) -> None:
    """Create the project, write the fixture KB, and pin the campaign root."""
    from lens.core.knowledge import KnowledgeStore

    session = setup_test_project(
        project_dir, llm_base_url, datasets=datasets, opening_write=False
    )
    storage = session.new_direct_edit_storage()
    store = KnowledgeStore.for_project(session.project_root, storage)
    for canonical_id, (body, tags) in KB_FIXTURES.items():
        store.store_object(canonical_id, body)
        if tags:
            store.add_tags(canonical_id, tags)
    storage.commit("prompt-lab fixtures")

    for pin_id in ROOT_PINS:
        lens("pin", "kb", "add", pin_id, cwd=project_dir)
    lens("commit", cwd=project_dir)


def run_scenario(scenario: Scenario, project_dir: Path, root_node: str) -> str:
    """Assemble *scenario* on a clean narrative and return the explain report.

    Scenarios must not leak into each other, and undoing a scenario's pins
    afterwards does not achieve that: the next ``lens rollback`` discards the
    *removal* along with everything else uncommitted, quietly restoring the pin.
    So each scenario is set up from the committed baseline instead — roll back,
    drop the sub-nodes the operators created, and restore the root node
    verbatim.
    """
    lens("rollback", cwd=project_dir, check=False)
    story = project_dir / "narrative" / "story"
    for stale in story.glob("*.md"):
        if stale.name != "_node.md":
            stale.unlink()
    (story / "_node.md").write_text(root_node, encoding="utf-8")

    for pin_id in scenario.pins:
        lens("pin", "kb", "add", pin_id, cwd=project_dir)

    if scenario.open_session:
        args = [scenario.operator, scenario.prompt]
        for key in scenario.modules:
            args += ["--module", key]
        lens(*args, cwd=project_dir)

    return lens(
        "explain", "--operator", scenario.operator, "--prompt", scenario.prompt,
        cwd=project_dir,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_TOTAL = re.compile(r"^TOTAL\s+([\d,]+)", re.MULTILINE)


def total_tokens(report: str) -> int | None:
    match = _TOTAL.search(report)
    return int(match.group(1).replace(",", "")) if match else None


def diff_against(baseline: Path, name: str, report: str) -> str | None:
    """Summarize how *report* moved against a saved baseline."""
    prior = baseline / f"{name}.txt"
    if not prior.exists():
        return "  (new scenario — no baseline)"
    before, after = total_tokens(prior.read_text(encoding="utf-8")), total_tokens(report)
    if before is None or after is None:
        return None
    delta = after - before
    if delta == 0:
        return "  total unchanged"
    pct = (delta / before * 100.0) if before else 0.0
    return f"  total {before:,} -> {after:,} tokens ({delta:+,}, {pct:+.1f}%)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble and measure realistic operator prompts.",
    )
    parser.add_argument("--out", type=Path, help="Directory to save each report into.")
    parser.add_argument(
        "--baseline", type=Path, help="Compare totals against reports saved by --out."
    )
    parser.add_argument(
        "--only", action="append", help="Scenario name (repeatable). Default: all."
    )
    parser.add_argument(
        "--datasets", default=",".join(DEFAULT_DATASETS), help="Comma-separated datasets."
    )
    parser.add_argument(
        "--keep", action="store_true", help="Keep the throwaway project and print its path."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Print only totals and deltas, not the tables."
    )
    args = parser.parse_args()

    wanted = set(args.only or [])
    scenarios = [s for s in SCENARIOS if not wanted or s.name in wanted]
    if not scenarios:
        print(f"no scenario matched {sorted(wanted)}", file=sys.stderr)
        print(f"available: {', '.join(s.name for s in SCENARIOS)}", file=sys.stderr)
        return 2

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    project_dir = Path(tempfile.mkdtemp(prefix="lens-prompt-lab-"))
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    try:
        with FakeLLMServer() as llm:
            build_project(project_dir, llm.base_url, datasets)
            root_node = (project_dir / "narrative" / "story" / "_node.md").read_text(
                encoding="utf-8"
            )
            for scenario in scenarios:
                report = run_scenario(scenario, project_dir, root_node)
                print(f"\n{'=' * 78}\n{scenario.name}  ({scenario.operator})\n{'=' * 78}")
                if not args.quiet:
                    print(report.rstrip())
                elif (tokens := total_tokens(report)) is not None:
                    print(f"  total {tokens:,} tokens")
                if args.baseline and (line := diff_against(args.baseline, scenario.name, report)):
                    print(line)
                if args.out:
                    (args.out / f"{scenario.name}.txt").write_text(report, encoding="utf-8")
        if args.out:
            print(f"\nReports saved to {args.out}")
    finally:
        if args.keep:
            print(f"Project kept at {project_dir}")
        else:
            shutil.rmtree(project_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
