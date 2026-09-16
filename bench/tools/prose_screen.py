#!/usr/bin/env python3
"""Screen generated prose cheaply, so reading attention goes where it counts.

Rating models on prose is limited by how carefully a person can read, not by
sampling cost (see issue #140). These two steps exist to protect that attention:
one removes the bias, the other removes the candidates that do not need reading.

Usage::

    # 1. Capture: one file per run, any layout, e.g. runs/01-ds-flash.md
    #    (a whole narrative node is fine — annotations are stripped below)

    # 2. Strip identifying blocks, shuffle, relabel A.md/B.md/... + write a key
    python bench/tools/prose_screen.py blind runs/ --out blind/ --key key.txt

    # 3. Screen mechanically before reading anything
    python bench/tools/prose_screen.py screen blind/ \\
        --project ../my-campaign --kb prep.enso-prologue --kb pc.enso \\
        --target-words 800

    # 4. Read and rank the blind files, THEN reveal
    python bench/tools/prose_screen.py reveal key.txt

``blind`` strips ``[... ]: #`` reference blocks (including ``>``-quoted ones) and
``<!-- ... -->`` comments, because the ``[write ...]`` annotation stores ``llm_id``
and the ``[llm-trace ...]`` block names the model and host outright.

``screen`` reports two signals that cost nothing and correlate well enough to
triage on:

* **lifted n-grams** — word-shingles shared with the prompt's own source text,
  stopword-only matches discarded. This is the "every character's eye colour
  every turn" failure measured instead of judged: a model reciting the KB it was
  handed rather than writing from it.
* **word count vs a stated target** — length compliance and instruction
  compliance turn out to be the same faculty, and length is free to measure.

Neither replaces reading. They decide what gets read first, and they catch lifts
a human reader misses (a 7-gram match is invisible at reading speed).
"""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
from pathlib import Path

# Shingle width. 7 is long enough that ordinary English does not collide and
# short enough to catch a lifted clause; 5 produces false positives on stock
# phrasing, 9 misses paraphrase-with-insertion.
DEFAULT_N = 7

# Matches on stopwords alone say nothing about recitation.
_STOPWORDS = frozenset(
    """the a an and or but of to in on at by for with from as is was were be been
    he she it his her him they them that this had has have not no so if then than
    there here when where which who whom what into over under up down out off""".split()
)

_ONE_LINE_BLOCK = re.compile(r"^\s*>?\s*\[.*\]:\s*#\s*$")
_BLOCK_OPEN = re.compile(r"^\s*>?\s*\[[A-Za-z0-9_:/-]*\s*$")
_BLOCK_CLOSE = re.compile(r"^\s*>?\s*\]:\s*#\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WORD = re.compile(r"[a-z']+")


def strip_blocks(text: str) -> str:
    """Remove annotation blocks and HTML comments, leaving prose.

    Quoted forms are handled too: a collated summary carries its body as a
    blockquote, and until recently the summary's own trace was quoted with it,
    where a ``>`` prefix hid it from ``strip_markdown_comments``.
    """
    text = _HTML_COMMENT.sub(" ", text)
    kept: list[str] = []
    in_block = False
    for line in text.splitlines():
        if _ONE_LINE_BLOCK.match(line):
            continue
        if _BLOCK_OPEN.match(line):
            in_block = True
            continue
        if in_block:
            if _BLOCK_CLOSE.match(line):
                in_block = False
            continue
        kept.append(line)
    return "\n".join(kept)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shingles(words: list[str], n: int) -> set[str]:
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _is_informative(shingle: str) -> bool:
    return not all(word in _STOPWORDS for word in shingle.split())


def cmd_blind(args: argparse.Namespace) -> int:
    src = Path(args.src)
    out = Path(args.out)
    files = sorted(p for p in src.glob("**/*.md") if p.is_file())
    if not files:
        print(f"no .md files under {src}", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.md"):
        stale.unlink()

    # Shuffle so the label order carries no information either: capture order
    # usually mirrors the order models were tried.
    rng = random.Random(args.seed)
    shuffled = list(files)
    rng.shuffle(shuffled)

    key_lines: list[str] = []
    for i, path in enumerate(shuffled):
        label = chr(ord("A") + i) if i < 26 else f"A{chr(ord('A') + i - 26)}"
        body = strip_blocks(path.read_text(encoding="utf-8")).strip() + "\n"
        (out / f"{label}.md").write_text(body, encoding="utf-8")
        key_lines.append(f"{label} = {path.name}")

    Path(args.key).write_text("\n".join(key_lines) + "\n", encoding="utf-8")
    print(f"{len(shuffled)} file(s) -> {out}/  (key: {args.key} — do not read it yet)")
    return 0


def cmd_reveal(args: argparse.Namespace) -> int:
    print(Path(args.key).read_text(encoding="utf-8").rstrip("\n"))
    return 0


def _kb_text(project: str, kb_id: str) -> str:
    result = subprocess.run(
        ["lens", "kb", "get", kb_id],
        capture_output=True,
        text=True,
        cwd=project,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"could not read {kb_id} from {project}: {result.stderr.strip()}")
    return result.stdout


def cmd_screen(args: argparse.Namespace) -> int:
    sources: list[str] = [Path(p).read_text(encoding="utf-8") for p in args.source]
    if args.kb:
        if not args.project:
            print("--kb requires --project", file=sys.stderr)
            return 1
        sources.extend(_kb_text(args.project, kb_id) for kb_id in args.kb)

    source_shingles: set[str] = _shingles(_words("\n".join(sources)), args.n) if sources else set[str]()

    rows: list[tuple[int, int, str, list[str]]] = []
    for path in sorted(Path(args.dir).glob("*.md")):
        words = _words(strip_blocks(path.read_text(encoding="utf-8")))
        lifted = sorted(s for s in _shingles(words, args.n) & source_shingles if _is_informative(s))
        rows.append((len(lifted), len(words), path.name, lifted))

    # Worst first: a reciter is the cheapest thing to drop before reading.
    for n_lifted, n_words, name, lifted in sorted(rows, key=lambda r: (-r[0], -r[1])):
        note = f"  ({n_words / args.target_words:.2f}x target)" if args.target_words else ""
        flag = "  <-- LIFT" if n_lifted else ""
        print(f"{name:<14} {n_words:>5}w{note}  {n_lifted} lifted {args.n}-gram(s){flag}")
        for sample in lifted[: args.show]:
            print(f'{"":<16}"{sample}"')
    if not sources:
        print("\n(no --source/--kb given: word counts only, no recitation check)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    blind = sub.add_parser("blind", help="strip identifying blocks, shuffle, relabel")
    blind.add_argument("src", help="directory of captured runs (*.md, searched recursively)")
    blind.add_argument("--out", required=True, help="directory for the anonymised copies")
    blind.add_argument("--key", required=True, help="where to write the label -> filename map")
    blind.add_argument("--seed", type=int, default=None, help="shuffle seed (default: random)")
    blind.set_defaults(func=cmd_blind)

    reveal = sub.add_parser("reveal", help="print the key, after ranking")
    reveal.add_argument("key")
    reveal.set_defaults(func=cmd_reveal)

    screen = sub.add_parser("screen", help="report lifted n-grams and word counts")
    screen.add_argument("dir", help="directory of prose to screen (usually the blind/ output)")
    screen.add_argument("--source", action="append", default=[], help="source text file the model was given (repeatable)")
    screen.add_argument("--kb", action="append", default=[], help="KB id the prompt pinned (repeatable; needs --project)")
    screen.add_argument("--project", default=None, help="Lens project dir to run `lens kb get` in")
    screen.add_argument("--target-words", type=int, default=0, help="stated length target, to report overshoot")
    screen.add_argument("-n", type=int, default=DEFAULT_N, help=f"shingle width (default {DEFAULT_N})")
    screen.add_argument("--show", type=int, default=2, help="example lifts to print per file")
    screen.set_defaults(func=cmd_screen)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
