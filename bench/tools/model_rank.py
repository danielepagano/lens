#!/usr/bin/env python3
"""Rank the models that survived the gate, across a *sequence* of beats.

The gate (``model_gate.py``) re-renders **one** beat per model, which is the
right shape for a disqualifier: a refusal arrives in the first breath. The two
things a ranking pass is actually for do not (issue #140) — prose stamina, and
the degeneration into the same three constructions whose canonical tell is every
character's eye colour every turn, only appear across *many* beats. So this tool
has the shape the gate does not: **each arm plays the whole sequence through, in
its own git branch**, and what is compared is a play-through rather than a beat.

That difference is load-bearing and it costs something. In the gate the arms are
the same beat with the same stored prompt, so they are comparable line by line.
Here they are not: arm B's beat 5 was written after arm B's beats 1–4, so every
arm has its own through-line. Only the **player lines are held identical**, which
is the level a sequence can be controlled at. Anything that compares two arms
beat-for-beat is reading noise.

What it measures, all of it mechanical and none of it a verdict:

* **words per beat, and the drift** from the opening beats to the closing ones.
  This is the column that earned its place: in the first real sweep it was the
  only number that separated the field *and* replicated at n=2 — one arm held
  its stated target to within 3%, one sat 18% over, and one shed a fifth then a
  third of its length by the closing beats. Length compliance and instruction
  compliance are the same faculty, and an instruction obeyed at beat two and
  forgotten at beat ten is exactly what a sequence is for.
* **recurring n-grams** — informative word-shingles that appear in three or more
  of an arm's beats, printed as a list. This is what caught the real failure: one
  arm ended beats it did not want to run with "roll initiative for Mara and
  report the result", three times per play-through, twice over. A three-beat
  boilerplate pattern is invisible at reading speed.
* **novelty** — the share of a beat's informative shingles unseen in that arm's
  earlier beats. Kept honest by measurement: it reads 99–100% for every arm of a
  decent field, so it is a **floor detector, not a stamina measure**, and it is
  deliberately not in the cross-arm table, where an aggregate that always says
  100% would invite ranking on noise. At n=5 verbatim shingles do not catch
  recycled *constructions*, which is what the eye-colour failure actually is.
  The list above does that job; this number only says a beat repeated itself
  outright.
* **what the generation cost**, read back out of the ``[llm-trace …]: #`` blocks
  the run itself banked: elapsed, reasoning characters, and the cached share of
  the prompt. The last of these is not decoration — one arm in the first sweep
  cached ~0% throughout while another held ~90%, which moves real cost by a
  factor a price list cannot show.

It does **not** score prose, and it deliberately grew no marker regexes beyond
that. The method names exactly two cheap pre-screens — verbatim overlap with the
pinned KB, and overshoot against a stated length target — and both already live
in ``prose_screen.py``, which is where the blind read goes next. A third, more
opinionated signal invented here would be the same mistake this repo has already
paid for once, when the gate disqualified a model for a line its *villain* said.

Reasoning is settled in the same pass, because the beats are being generated
anyway: an arm is ``<llm-id>`` or ``<llm-id>:<effort>``, and the effort is passed
as ``lens play --reasoning``. That is safe in the one place it looks unsafe — a
candidate that cannot run with thinking off is protected by ``reasoning_floor``
on its own ``[[llm]]`` row, which clamps upward and cannot be lowered by an
invocation. Sort the arms by the **reasoning characters** the trace reports, not
by the effort label: the label is a blunt dial on the variable that actually
predicts quality.

Usage::

    # 1. Build the project and its cast (repo root)
    PROJECT=$(python bench/tools/setup_bench.py --profile deepseek \\
        --scenario bench/scenarios/model_rank.md)
    export PROJECT && bash bench/scenarios/model_rank_setup.sh

    # 2. Wire the survivors as named [[llm]] rows in $PROJECT/lens.toml, then:
    python bench/tools/model_rank.py --project "$PROJECT" \\
        --arm ds-flash --arm ds-flash:high --arm glm-flash \\
        --target-words 180 --out bench/reports/rank/

    # 3. Read blind FIRST. With --out the sweep holds its own measurements back,
    #    because the table names each arm beside its word counts and that is
    #    enough to map the banked files — which is how the first real sweep
    #    de-blinded the person reading it.
    python bench/tools/prose_screen.py blind bench/reports/rank/ \\
        --out blind/ --key key.txt
    python bench/tools/prose_screen.py screen blind/ --project "$PROJECT" \\
        --kb location.cinder-yard --kb npc.vetch --target-words 1800
    # …rank by reading, and only then:
    python bench/tools/prose_screen.py reveal key.txt

    # 4. Now the numbers. Re-analysis is free and the first pass will be wrong:
    python bench/tools/model_rank.py --rescore bench/reports/rank/ --target-words 180

Two samples per arm, minimum. Within-model variance on creative output rivals
between-model variance, so one play-through per arm measures noise. Run the
sweep twice with different ``--out`` directories rather than trusting a single
pass — and note that the arms' branches are left behind on purpose, so a second
sweep wants ``--branch-prefix`` or a fresh project.
"""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The shingle machinery is shared with prose_screen rather than copied: the
# stopword list and the width are the measurement, and two copies would drift
# into two different measurements reported under one name.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prose_screen import informative_shingles, prose_words  # noqa: E402

# Narrower than prose_screen's 7. That width is tuned for a *lifted clause* out
# of a source text, where ordinary English must not collide. This measures an
# arm reciting itself, where a recycled construction is the thing being caught
# and is shorter than a clause — "his hands stay still", "the ash never
# settles". Collisions are the signal here rather than the noise.
DEFAULT_N = 5

# Every arm's session gets the same slug, because isolation is by branch: the
# banked file names stay uniform and a diff across two branches lines up.
SESSION_SLUG = "rank"

_STEP_HEADING = re.compile(r"^###\s+`([A-Za-z0-9_-]+)`\s*$")
_FENCE = re.compile(r"^```(\w*)\s*$")

_PLAYER_LINE = re.compile(r"^\s*>\s*\[Player\]", re.IGNORECASE)
_TRACE_OPEN = re.compile(r"^\s*\[llm-trace\s*$")
_BLOCK_CLOSE = re.compile(r"^\s*\]:\s*#\s*$")
_YAML_ROW = re.compile(r"^(\s+)([A-Za-z_]+):\s*(\S.*)?$")

_ARM_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_EFFORTS = ("none", "low", "medium", "high")


@dataclass(frozen=True)
class Beat:
    """One player line in the sequence. The scenario owns the wording."""

    beat_id: str
    command: str


@dataclass(frozen=True)
class Arm:
    """A model, optionally at a stated reasoning effort."""

    llm_id: str
    effort: str = ""

    @property
    def arm_id(self) -> str:
        return f"{self.llm_id}-{self.effort}" if self.effort else self.llm_id


@dataclass
class BeatResult:
    """What one generated beat weighed, and what the provider said it cost."""

    index: int
    beat_id: str
    words: int = 0
    novel: float = 0.0
    """Share of this beat's informative shingles unseen in the arm's earlier beats."""
    shingles: set[str] = field(default_factory=lambda: set[str]())
    elapsed_ms: int = 0
    reasoning_chars: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""
    effort: str = ""


@dataclass
class ArmResult:
    arm_id: str
    beats: list[BeatResult] = field(default_factory=lambda: list[BeatResult]())
    error: str = ""
    folded: bool = False
    """True when the session became a folder node — auto-compress moved beats."""


# ---------------------------------------------------------------------------
# scenario
# ---------------------------------------------------------------------------


def parse_beats(scenario: Path) -> list[Beat]:
    """Read the ordered ``### `id`` steps, each with one ```bash block.

    The same grammar the other play scenarios already use, minus the gate's
    ``scene`` block: a sequence has *one* opening passage, committed by the
    setup script, and every beat after that is played into the scene the
    previous beat left behind. Order in the file is the order played.
    """
    beats: list[Beat] = []
    beat_id: str | None = None
    command: str | None = None
    fence: str | None = None
    buf: list[str] = []

    for line in scenario.read_text(encoding="utf-8").splitlines():
        if fence is not None:
            if line.strip() == "```":
                if fence == "bash" and command is None:
                    command = "\n".join(buf).strip()
                fence, buf = None, []
            else:
                buf.append(line)
            continue
        fence_match = _FENCE.match(line)
        if fence_match and beat_id:
            fence = fence_match.group(1) or "text"
            buf = []
            continue
        heading = _STEP_HEADING.match(line)
        if heading:
            if beat_id and command:
                beats.append(Beat(beat_id, command))
            beat_id, command = heading.group(1), None

    if beat_id and command:
        beats.append(Beat(beat_id, command))
    return beats


def check_beats(beats: list[Beat]) -> None:
    """Reject a malformed sequence before a single call is paid for.

    This used to be checked inside the loop, where the first bad command raised
    part-way through an arm — after money had been spent, and with the tree left
    mid-beat on that arm's branch. A `### heading` added to a later section of
    the scenario is enough to produce one.
    """
    for beat in beats:
        if shlex.split(beat.command)[:2] != ["lens", "play"]:
            raise SystemExit(
                f"{beat.beat_id}: expected a `lens play` command, got: {beat.command}"
            )


def parse_arm(spec: str) -> Arm:
    llm_id, _, effort = spec.partition(":")
    if not _ARM_ID.match(llm_id):
        raise SystemExit(f"not an [[llm]] id: {llm_id!r}")
    if effort and effort not in _EFFORTS:
        raise SystemExit(f"{spec}: effort must be one of {', '.join(_EFFORTS)}")
    return Arm(llm_id, effort)


# ---------------------------------------------------------------------------
# reading a banked play-through
# ---------------------------------------------------------------------------


def parse_trace(chunk: str) -> dict[str, str]:
    """Flatten the first ``[llm-trace …]: #`` block in *chunk* to ``key: value``.

    Nested keys are prefixed (``usage.cached_tokens``, ``reasoning.chars``). The
    block is strict YAML at a fixed two-space indent precisely so it can be read
    back, and reading it back is the only way to know what a generation cost —
    the numbers come from the provider, not from an estimate over character
    counts.
    """
    out: dict[str, str] = {}
    lines = chunk.splitlines()
    for i, line in enumerate(lines):
        if not _TRACE_OPEN.match(line):
            continue
        section = ""
        for row in lines[i + 1 :]:
            if _BLOCK_CLOSE.match(row):
                return out
            match = _YAML_ROW.match(row)
            if not match:
                continue
            indent, key, value = match.group(1), match.group(2), match.group(3)
            if value is None:
                section = key if len(indent) <= 2 else section
                continue
            out[f"{section}.{key}" if len(indent) > 2 and section else key] = value.strip()
        return out
    return out


def split_beats(node_text: str) -> list[str]:
    """Split a play node into one chunk per beat, at the player's own lines.

    ``play`` writes the player line as ``> [Player] …`` *outside* the operator
    block, which makes it the only reliable beat boundary — the annotation ids
    differ per arm and the trace is optional.
    """
    chunks: list[list[str]] = []
    for line in node_text.splitlines():
        if _PLAYER_LINE.match(line):
            chunks.append([])
        if chunks:
            chunks[-1].append(line)
    return ["\n".join(c) for c in chunks]


def measure_arm(arm_id: str, node_text: str, beats: list[Beat], n: int) -> ArmResult:
    """Turn a banked play-through into per-beat numbers. No model is called."""
    result = ArmResult(arm_id=arm_id)
    seen: set[str] = set()
    for i, chunk in enumerate(split_beats(node_text)):
        # Drop the player's line before counting: it is identical across every
        # arm by construction, so counting it would flatten the differences
        # this tool exists to show.
        body = "\n".join(
            line for line in chunk.splitlines() if not _PLAYER_LINE.match(line)
        )
        words = prose_words(body)
        shingles = informative_shingles(words, n)
        trace = parse_trace(chunk)
        beat = BeatResult(
            index=i + 1,
            beat_id=beats[i].beat_id if i < len(beats) else f"beat-{i + 1}",
            words=len(words),
            novel=(len(shingles - seen) / len(shingles)) if shingles else 0.0,
            shingles=shingles,
            elapsed_ms=int(trace.get("elapsed_ms", 0) or 0),
            reasoning_chars=int(trace.get("reasoning.chars", 0) or 0),
            prompt_tokens=int(trace.get("usage.prompt_tokens", 0) or 0),
            cached_tokens=int(trace.get("usage.cached_tokens", 0) or 0),
            model=trace.get("model", ""),
            effort=trace.get("reasoning_effort", ""),
        )
        seen |= shingles
        result.beats.append(beat)
    return result


# ---------------------------------------------------------------------------
# running the sweep
# ---------------------------------------------------------------------------


def _git(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, check=check
    )


def _lens(
    project: Path, *args: str, timeout: float = 900
) -> subprocess.CompletedProcess[str]:
    """Run a lens command, treating a hang as a result rather than an exception.

    A sweep is arms times beats and runs for the better part of an hour of paid
    calls. One model that never returns must not take the rest of it down: some
    candidates stream a very long reasoning trace, and a first-token timeout
    does not bound the whole reply.
    """
    try:
        return subprocess.run(
            ["lens", *args], cwd=project, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=["lens", *args],
            returncode=124,
            stdout="",
            stderr=f"timed out after {timeout:.0f}s",
        )


def _guard_throwaway(project: Path) -> None:
    """Refuse to sweep anywhere a ``git reset --hard`` would be a disaster.

    Arms are isolated by resetting the tree to a base commit, which is only ever
    the right thing to do in a throwaway bench project. A bench project has a
    ``lens.toml`` and no ``pyproject.toml``; the Lens repo itself has both a
    ``pyproject.toml`` and a ``lens/`` package, and a mistyped ``--project``
    pointing at it would be unrecoverable.
    """
    if not (project / "lens.toml").is_file():
        raise SystemExit(f"{project} has no lens.toml — not a Lens project")
    if (project / "pyproject.toml").is_file() or (project / "lens" / "core").is_dir():
        raise SystemExit(
            f"{project} looks like the Lens source repo, not a bench project.\n"
            "Arms reset the tree to a base commit; refusing to do that here."
        )


def _ensure_base(project: Path) -> str:
    """Commit whatever setup left behind, and return the base commit.

    The setup scripts end in ``lens commit``, which *stages* rather than
    commits, so the cast is sitting in the index. Committing it is the
    non-destructive way to make it the base every arm branches from — the
    alternative, discarding it, would silently sweep an empty project.
    """
    if _git(project, "status", "--porcelain").stdout.strip():
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "rank: base", check=False)
    head = _git(project, "rev-parse", "HEAD").stdout.strip()
    if not head:
        raise SystemExit(f"{project} has no commits")
    return head


def _current_ref(project: Path) -> str:
    branch = _git(project, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return branch.stdout.strip() or _git(project, "rev-parse", "HEAD").stdout.strip()


def _start_arm(project: Path, branch: str, base: str) -> None:
    """Put the tree back at *base* and open *branch* on top of it.

    Detaching first is not tidiness. A ``reset --hard`` while HEAD is still on
    the previous arm's branch moves *that branch* back to the base and throws
    away the play-through it had just recorded — silently, because the banked
    ``--out`` copy was already written and the report still looks right.
    ``-f`` on the detach does the discarding instead, where it can only affect
    a detached HEAD.
    """
    _git(project, "checkout", "-q", "-f", "--detach", base)
    _git(project, "clean", "-fdq")
    _git(project, "checkout", "-q", "-B", branch, base)


def _session_node(project: Path) -> tuple[Path | None, bool]:
    """Locate the arm's session node. Second value is True for a folder node."""
    leaf = next(project.glob(f"narrative/*/play-{SESSION_SLUG}.md"), None)
    if leaf is not None:
        return leaf, False
    folded = next(project.glob(f"narrative/*/play-{SESSION_SLUG}/_node.md"), None)
    return folded, folded is not None


def _session_text(project: Path) -> tuple[str, bool]:
    """Read the play-through. A folder node means the sequence was collated.

    The setup script turns auto-compress off precisely so this cannot happen,
    because a collate rewrites the node as *before + summary + tail* and moves
    the verbatim middle into a child file — so there is no concatenation of the
    two that puts the beats back in the order they were played, and every
    order-dependent number here (novelty accumulates; drift compares the first
    beats against the last) would be quietly wrong rather than merely coarse.
    The children are still read, because the banked text should be complete for
    someone reading it, but the flag voids the measurement.
    """
    node, folded = _session_node(project)
    if node is None:
        return "", False
    parts = [node.read_text(encoding="utf-8")]
    if folded:
        parts.extend(
            child.read_text(encoding="utf-8")
            for child in sorted(node.parent.glob("*.md"))
            if child.name != "_node.md"
        )
    return "\n".join(parts), folded


def run_arm(
    project: Path,
    arm: Arm,
    beats: list[Beat],
    base: str,
    branch_prefix: str,
    out: Path | None,
    timeout: float,
    n: int = DEFAULT_N,
) -> ArmResult:
    branch = f"{branch_prefix}/{arm.arm_id}"
    _start_arm(project, branch, base)

    error = ""
    for i, beat in enumerate(beats):
        args = shlex.split(beat.command)[2:]
        if i == 0:
            args += ["--slug", SESSION_SLUG]
        args += ["--llm", arm.llm_id]
        if arm.effort:
            args += ["--reasoning", arm.effort]
        result = _lens(project, "play", *args, timeout=timeout)
        if result.returncode != 0:
            # The sequence is the unit of measurement, so a failed beat ends the
            # arm rather than leaving a hole in the middle of it: every later
            # beat would be played into a scene that never happened.
            error = f"beat {i + 1} ({beat.beat_id}): {result.stderr.strip()[-200:]}"
            print(f"  !!! {error}", flush=True)
            break
        # Deliberately no word count here. A live cumulative-words line is
        # enough on its own to map the banked files back to their arms, and the
        # first real sweep did exactly that to the person reading it.
        print(f"  ... {i + 1:>2}/{len(beats)} {beat.beat_id:<20} ok", flush=True)

    _lens(project, "commit")
    _git(project, "commit", "-q", "-m", f"rank: {arm.arm_id}", check=False)
    if _git(project, "rev-parse", "HEAD").stdout.strip() == base:
        # The docstring promises the branch is the record of this play-through
        # and that two of them can be diffed. If nothing landed on it, say so —
        # the banked copy and the report both read the working tree, so this
        # failure is otherwise invisible until someone tries that diff.
        print(f"  !!! nothing was committed to {branch} — it is not a record", flush=True)

    node_text, folded = _session_text(project)
    if out and node_text:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{arm.arm_id}.md").write_text(node_text, encoding="utf-8")

    measured = measure_arm(arm.arm_id, node_text, beats, n)
    measured.error = error
    measured.folded = folded
    return measured


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _edge(n_beats: int) -> int:
    """How many beats count as "the opening" and "the close" of a sequence."""
    return max(1, n_beats // 3)


def _drift(arm: ArmResult) -> float:
    """Change in words per beat from the arm's opening beats to its closing ones.

    This is the column that earned its place. Across the first real sweep it was
    the only number that both separated the field and replicated at n=2: one arm
    held its stated target to within 3%, one sat 18% over it, and one shed a
    fifth to a third of its length by the closing beats — twice. An instruction
    obeyed at beat two and forgotten by beat ten is what a sequence is for, and
    this is that, measured for nothing.
    """
    edge = _edge(len(arm.beats))
    words = [float(b.words) for b in arm.beats]
    opening = _mean(words[:edge])
    return (_mean(words[-edge:]) / opening - 1) if opening else 0.0


def _row(*cells: str) -> str:
    """One fixed-width row of the per-beat table, header and body alike."""
    widths = (4, 22, 7, 6, 6, 8, 6)
    return "  " + " ".join(
        cell.ljust(width) if i == 1 else cell.rjust(width)
        for i, (cell, width) in enumerate(zip(cells, widths, strict=True))
    )


def _report(arms: list[ArmResult], target_words: int, n: int) -> None:
    for arm in arms:
        print(f"\n=== {arm.arm_id} — {len(arm.beats)} beat(s)")
        if arm.error:
            print(f"  incomplete: {arm.error}")
        if arm.folded:
            print(
                "  the sequence was collated into a child node, so the order the beats"
                "\n  were played in cannot be reconstructed and every per-beat number"
                "\n  here would be wrong rather than coarse. The banked text is complete"
                "\n  — read it, and check [compress] auto_compress = false before"
                "\n  sampling this arm again."
            )
            continue
        if not arm.beats:
            continue
        print(_row("#", "beat", "words", "novel", "s", "rsn", "cache"))
        for b in arm.beats:
            cached = f"{100 * b.cached_tokens / b.prompt_tokens:.0f}%" if b.prompt_tokens else "-"
            print(
                _row(
                    str(b.index),
                    b.beat_id,
                    str(b.words),
                    f"{b.novel:.0%}",
                    f"{b.elapsed_ms / 1000:.1f}",
                    str(b.reasoning_chars),
                    cached,
                )
            )
        words = [float(b.words) for b in arm.beats]
        edge = _edge(len(arm.beats))
        drift = _drift(arm)
        novel_open, novel_close = (
            _mean([b.novel for b in arm.beats[:edge]]),
            _mean([b.novel for b in arm.beats[-edge:]]),
        )
        print(
            _row(
                "",
                "mean",
                f"{_mean(words):.0f}",
                f"{_mean([b.novel for b in arm.beats]):.0%}",
                f"{_mean([b.elapsed_ms / 1000 for b in arm.beats]):.1f}",
                f"{_mean([float(b.reasoning_chars) for b in arm.beats]):.0f}",
                "",
            )
        )
        target = f", {_mean(words) / target_words:.2f}x target" if target_words else ""
        print(
            f"  last {edge} vs first {edge}: words {drift:+.0%}{target},"
            f" novelty {novel_close - novel_open:+.0%}"
        )
        repeats = _top_repeats(arm)
        if repeats:
            # Promoted above the novelty number on purpose. In the first real
            # sweep the percentages sat at 99–100% for every arm and said
            # nothing, while this list pointed straight at one arm ending beats
            # it did not want to run with "roll initiative for Mara and report
            # the result" — three times per play-through, twice over. The list
            # is also the only thing that can tell the scene recurring (the
            # stove, the top of the pass) from the model recurring.
            print(f"  recurring {n}-grams (beats they appear in) — read these:")
            for shingle, count in repeats:
                print(f'    {count}x  "{shingle}"')


def _top_repeats(arm: ArmResult, limit: int = 5) -> list[tuple[str, int]]:
    """Informative shingles that recur across three or more of the arm's beats.

    The number says a beat repeated itself; this says *what* it repeated, which
    is what a person needs to decide whether it is the cast's name recurring
    because the cast recurs, or the same sentence being written for the ninth
    time.
    """
    counts: dict[str, int] = {}
    for beat in arm.beats:
        for shingle in beat.shingles:
            counts[shingle] = counts.get(shingle, 0) + 1
    ranked = sorted(
        ((s, c) for s, c in counts.items() if c >= 3), key=lambda r: (-r[1], r[0])
    )
    return ranked[:limit]


def _arm_row(*cells: str) -> str:
    """One fixed-width row of the cross-arm summary."""
    widths = (20, 5, 14, 6, 7, 9)
    return "  " + " ".join(
        cell.ljust(width) if i == 0 else cell.rjust(width)
        for i, (cell, width) in enumerate(zip(cells, widths, strict=True))
    )


def _summary(arms: list[ArmResult], target_words: int) -> None:
    print("\n=== arms ===")
    print(_arm_row("arm", "beats", "words/beat", "drift", "s/beat", "rsn/beat"))
    for arm in arms:
        if arm.folded:
            print(f"  {arm.arm_id:<20} {'-':>5}  collated mid-sequence — see above")
            continue
        if not arm.beats:
            print(f"  {arm.arm_id:<20} {'-':>5}  {arm.error or 'no beats'}")
            continue
        words = _mean([float(b.words) for b in arm.beats])
        note = f" ({words / target_words:.2f}x)" if target_words else ""
        print(
            _arm_row(
                arm.arm_id,
                str(len(arm.beats)),
                f"{words:.0f}{note}",
                f"{_drift(arm):+.0%}",
                f"{_mean([b.elapsed_ms / 1000 for b in arm.beats]):.1f}",
                f"{_mean([float(b.reasoning_chars) for b in arm.beats]):.0f}",
            )
        )
    print(
        "\nNo verdicts, and none of these numbers is a ranking. `drift` is the one"
        "\nthat has separated a field and replicated; per-beat `novel` is a floor"
        "\ndetector, not a stamina measure — it read 99–100% for every arm in the"
        "\nfirst real sweep, and the recurring-n-gram lists did that work instead."
        "\nReasoning characters, not the effort label, order arms by volume."
        "\nWhat decided the first sweep was reading one beat. These numbers said"
        "\nwhich beat."
    )


def _rescore(banked: Path, scenario: Path, n: int, target_words: int) -> int:
    files = sorted(banked.glob("*.md"))
    if not files:
        print(f"no banked play-throughs (<arm>.md) under {banked}", file=sys.stderr)
        return 1
    beats = parse_beats(scenario) if scenario.is_file() else []
    arms = [
        measure_arm(f.stem, f.read_text(encoding="utf-8"), beats, n) for f in files
    ]
    print(f"rescored {len(arms)} banked play-through(s) from {banked}")
    _report(arms, target_words, n)
    _summary(arms, target_words)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project", default=None, help="bench project dir (from setup_bench.py)")
    parser.add_argument(
        "--arm",
        action="append",
        default=[],
        metavar="ID[:EFFORT]",
        help="an [[llm]] id, optionally at a reasoning effort (repeatable)",
    )
    parser.add_argument(
        "--rescore",
        default=None,
        metavar="DIR",
        help="re-read a banked --out directory and measure it again, without sampling",
    )
    parser.add_argument(
        "--scenario",
        default="bench/scenarios/model_rank.md",
        help="scenario holding the beat sequence (default: %(default)s)",
    )
    parser.add_argument("--out", default=None, help="directory to bank each arm's play-through in")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="play only the first N beats (default: the whole sequence)",
    )
    parser.add_argument(
        "--target-words",
        type=int,
        default=0,
        help="length target stated in the scene, to report overshoot against",
    )
    parser.add_argument(
        "-n", type=int, default=DEFAULT_N, help=f"shingle width for novelty (default {DEFAULT_N})"
    )
    parser.add_argument(
        "--branch-prefix",
        default="bench-rank",
        help="prefix for each arm's branch (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900,
        help="seconds to allow one beat before ending the arm (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the beats and arms that would run, and call nothing",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print the measurements at the end of a banked sweep, instead of holding"
        " them behind --rescore so the bank can be read blind first",
    )
    args = parser.parse_args(argv)

    scenario = Path(args.scenario)

    # Sampling costs money and re-analysis is free, which is the whole reason a
    # play-through is banked: the first reading of it will be wrong.
    if args.rescore:
        return _rescore(Path(args.rescore), scenario, args.n, args.target_words)

    beats = parse_beats(scenario)
    if not beats:
        print(f"no beats found in {scenario}", file=sys.stderr)
        return 1
    check_beats(beats)
    if args.limit:
        beats = beats[: args.limit]
    arms = [parse_arm(spec) for spec in args.arm]

    if args.dry_run:
        print(f"{len(arms)} arm(s) x {len(beats)} beat(s) from {scenario}")
        for arm in arms:
            print(f"  arm {arm.arm_id:<20} --llm {arm.llm_id}" + (f" --reasoning {arm.effort}" if arm.effort else ""))
        for i, beat in enumerate(beats, 1):
            print(f"  {i:>3} {beat.beat_id:<22} {beat.command}")
        return 0

    if not args.project or not arms:
        parser.error("--project and at least one --arm are required unless --rescore is given")
    if not shutil.which("lens"):
        print("lens is not on PATH", file=sys.stderr)
        return 1

    project = Path(args.project).resolve()
    _guard_throwaway(project)
    out = Path(args.out).resolve() if args.out else None
    if out is not None and out.is_relative_to(project):
        # Each arm starts with `git clean -fdq`, which would delete a banked
        # directory sitting inside the project as untracked. Sampling is the
        # expensive half of this loop; losing it to a tidy-up is not a failure
        # anyone should have to diagnose twice.
        raise SystemExit(f"--out must be outside the project: {out}")
    origin = _current_ref(project)
    base = _ensure_base(project)

    results: list[ArmResult] = []
    try:
        for arm in arms:
            print(f"\n=== {arm.arm_id} ({len(beats)} beats) ===", flush=True)
            results.append(
                run_arm(
                    project,
                    arm,
                    beats,
                    base,
                    args.branch_prefix,
                    out,
                    args.timeout,
                    args.n,
                )
            )
    finally:
        # Leave every arm's branch behind — it is the record of that
        # play-through and a diff between two of them is readable — but put the
        # working tree back where it was found. Forced, because an exception
        # part-way through an arm leaves the tree mid-beat and a plain checkout
        # would refuse, silently stranding the project on an arm's branch.
        restore = _git(project, "checkout", "-q", "-f", origin, check=False)
        if restore.returncode != 0:
            print(
                f"could not return {project} to {origin}: {restore.stderr.strip()}",
                file=sys.stderr,
            )

    if out is not None and not args.report:
        # The method commits to scoring blind, and this table names the model
        # next to its word counts — which is enough to map the banked files
        # back to their arms. The first real sweep de-blinded its own reader
        # that way. So when the beats were banked *for* a blind read, the
        # numbers wait behind --rescore; nothing is lost, because re-measuring
        # a bank costs nothing.
        print(f"\n=== banked {len(results)} play-through(s) to {out}")
        for arm in results:
            if arm.error:
                print(f"  {arm.arm_id:<20} incomplete: {arm.error}")
            elif arm.folded:
                print(f"  {arm.arm_id:<20} collated mid-sequence — measurement void")
            else:
                print(f"  {arm.arm_id:<20} {len(arm.beats)} beat(s)")
        print(
            "\nRead it blind before you look at the numbers — this table would name"
            "\nthe arms by their word counts:"
            f"\n  python bench/tools/prose_screen.py blind {out} --out blind/ --key key.txt"
            "\n  python bench/tools/prose_screen.py screen blind/ --project <project> --kb <id>"
            "\n  python bench/tools/prose_screen.py reveal key.txt"
            f"\n\nThen the measurements, for free:"
            f"\n  python bench/tools/model_rank.py --rescore {out} --target-words {args.target_words}"
        )
        return 0

    _report(results, args.target_words, args.n)
    _summary(results, args.target_words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
