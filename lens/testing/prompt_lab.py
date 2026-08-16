"""Prompt lab: measure what a prompt change does to an assembled context.

Editing ``lens/prompts/default.toml``, a ``design.*`` module, a ``rules.*``
booklet or a ``_template`` is editing an **LLM prompt**.  The diff is not the
artifact — the assembled context is, and nothing in the test suite asserts on
it.  Reading a diff cannot tell you that a module now costs 800 more tokens,
that a booklet stopped being reachable, or that a ``rules.<type>`` companion
quietly stopped firing.

This owns **no content of its own**.  It is a sweep over ``lens explain``
against a project that bench already knows how to build, so the material comes
from the datasets and bench scenarios that are maintained anyway::

    poe prompt-lab -- --scenario bench/scenarios/play_dnd_rules_split.md
    poe prompt-lab -- --project bench/projects/lens_bench_xyz -o play -o design

The point is the before/after, not the absolute number::

    poe prompt-lab -- --scenario … --out /tmp/before
    #  …edit prompts / modules / templates…
    poe prompt-lab -- --scenario … --baseline /tmp/before

Every step shells out to the CLI on purpose.  ``KnowledgeStore`` caches its tag
index per project, so writing KB objects and then crawling in the same process
can read stale tags and show a ``+`` expansion resolving to nothing — which is
indistinguishable from a real bug.  A subprocess always reads the world as a
user would.

``lens explain`` assembles the prompt exactly as the operator would and
measures it instead of calling a model, so a sweep needs no LLM at all.  A
model is only involved when ``--module`` asks for a session to be opened first,
and then only to end the turn: point ``--profile`` at ``llm_mock`` and run
``poe mock-llm`` alongside.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SETUP_BENCH = _REPO_ROOT / "bench" / "tools" / "setup_bench.py"
_LENS = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

_TOTAL = re.compile(r"^TOTAL\s+([\d,]+)", re.MULTILINE)


def lens(*args: str, cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(
        [*_LENS, *args], cwd=cwd, capture_output=True, text=True, timeout=300
    )
    if check and proc.returncode != 0:
        raise SystemExit(
            f"lens {' '.join(args)} failed ({proc.returncode})\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


def setup_from_bench(scenario: Path | None, profile: str) -> Path:
    """Build a bench project and run the scenario's Setup, returning its path.

    Delegates entirely to ``bench/tools/setup_bench.py`` and the scenario's own
    ``_setup.sh``: datasets, KB objects, pins and narrative all come from there.
    """
    cmd = [sys.executable, str(_SETUP_BENCH), "--profile", profile]
    if scenario is not None:
        cmd += ["--scenario", str(scenario)]
    proc = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"setup_bench failed:\n{proc.stdout}\n{proc.stderr}")
    project_dir = Path(proc.stdout.strip().splitlines()[-1])

    if scenario is not None:
        setup_sh = scenario.with_name(f"{scenario.stem}_setup.sh")
        if setup_sh.exists():
            run = subprocess.run(
                ["bash", str(setup_sh)],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                env={**_env(), "PROJECT": str(project_dir)},
            )
            if run.returncode != 0:
                raise SystemExit(
                    f"{setup_sh.name} failed:\n{run.stdout}\n{run.stderr}"
                )
    return project_dir


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


def sweep(
    project_dir: Path,
    operators: list[str],
    modules: list[str],
    prompt: str | None,
    address: str | None,
) -> dict[str, str]:
    """Return ``{label: explain report}`` for each operator asked for."""
    reports: dict[str, str] = {}
    for operator in operators:
        label = operator if not modules else f"{operator}-{'-'.join(modules)}"
        if modules:
            args = [operator, prompt or f"prompt-lab {operator} sweep"]
            for key in modules:
                args += ["--module", key]
            lens(*args, cwd=project_dir)
        explain = ["explain", "--operator", operator]
        if prompt:
            explain += ["--prompt", prompt]
        if address:
            explain.append(address)
        reports[label] = lens(*explain, cwd=project_dir)
    return reports


def total_tokens(report: str) -> int | None:
    match = _TOTAL.search(report)
    return int(match.group(1).replace(",", "")) if match else None


def compare(baseline: Path, label: str, report: str) -> str | None:
    prior = baseline / f"{label}.txt"
    if not prior.exists():
        return "  (no baseline for this label)"
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
        description="Assemble and measure operator prompts over a bench project.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--scenario",
        type=Path,
        help="Bench scenario whose config + Setup builds the project (bench/scenarios/*.md).",
    )
    source.add_argument(
        "--project",
        type=Path,
        help="An existing project directory to measure instead of building one.",
    )
    parser.add_argument(
        "--profile",
        default="llm_mock",
        help="Bench LLM profile for the built project (default: llm_mock).",
    )
    parser.add_argument(
        "--operator",
        "-o",
        action="append",
        help="Operator to assemble for (repeatable). Default: the cursor's own.",
    )
    parser.add_argument(
        "--module",
        "-m",
        action="append",
        help="Open a session with these modules first (repeatable). Needs a live LLM.",
    )
    parser.add_argument("--prompt", "-p", help="Prompt text to assemble with.")
    parser.add_argument("--address", "-a", help="Narrative address to explain at.")
    parser.add_argument("--out", type=Path, help="Directory to save each report into.")
    parser.add_argument(
        "--baseline", type=Path, help="Compare totals against reports saved by --out."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Print totals and deltas, not the tables."
    )
    args = parser.parse_args()

    if args.project is not None:
        project_dir = args.project
        if not (project_dir / "lens.toml").exists():
            raise SystemExit(f"{project_dir} is not a Lens project")
    else:
        project_dir = setup_from_bench(args.scenario, args.profile)
        print(f"Project: {project_dir}\n")

    operators = args.operator or [""]
    if operators == [""]:
        # No operator given: let explain detect the one that owns the cursor.
        report = lens(
            *(["explain"] + (["--prompt", args.prompt] if args.prompt else [])),
            cwd=project_dir,
        )
        reports = {"cursor": report}
    else:
        reports = sweep(
            project_dir, operators, args.module or [], args.prompt, args.address
        )

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    for label, report in reports.items():
        print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
        if args.quiet:
            if (tokens := total_tokens(report)) is not None:
                print(f"  total {tokens:,} tokens")
        else:
            print(report.rstrip())
        if args.baseline and (line := compare(args.baseline, label, report)):
            print(line)
        if args.out:
            (args.out / f"{label}.txt").write_text(report, encoding="utf-8")

    if args.out:
        print(f"\nReports saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
