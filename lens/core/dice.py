"""Dice roll substitution for prompts.

Replaces ``@roll <expr>`` and ``@roll(<expr>)`` tokens in a prompt string
with ``rolled <expr>=<result>`` (or ``calculated …`` when the expression
contains no dice notation — no ``d``) before the prompt is sent to the LLM.
The dice library (https://github.com/borntyping/python-dice) evaluates the expression.

This is a user-side convenience feature — the LLM never sees the @roll
syntax, only the substituted bracket text.

All dice rolls share one :class:`random.Random` instance created at import
time (Mersenne Twister, seeded once by the interpreter — not a CSPRNG, but
fine for narrative dice). That avoids relying on the process-wide
:mod:`random` module or constructing a new generator per substitution.
"""

from __future__ import annotations

import random
import re
from typing import Any, cast

import dice  # type: ignore[import-untyped]

_DICE_RNG = random.Random()

# Matches either:
#   @roll (<expression>)  — parenthesised form, allows spaces in expression
#   @roll <expression>    — bare form, space required, expression until next space
_DICE_ROLL_RE = re.compile(
    r"@roll\s+\(([^)]+)\)"  # parenthesised: @roll (expr) or @roll(expr)
    r"|"
    r"@roll\s+(\S+)",       # bare: @roll expr
)


class DiceError(Exception):
    """Raised when a @roll expression cannot be evaluated."""


def _roll_to_text(expr: str, *, rng: random.Random) -> str:
    """Evaluate a dice expression and return a display-ready result."""
    raw: object = dice.roll(expr, random=rng)  # type: ignore[no-untyped-call]
    # Keep list-like roll outputs as-is so systems that rely on roll operators
    # see the library's own rendered result instead of a forced re-sum.
    if isinstance(raw, list):
        return str(cast(list[Any], raw))
    return str(int(cast(Any, raw)))


def substitute_rolls(prompt: str, *, rng: random.Random | None = None) -> str:
    """Replace all ``@roll`` expressions in *prompt* with their results.

    Uses a single module-level :class:`~random.Random` unless *rng* is given
    (tests may pass a seeded instance for determinism).

    Raises :class:`DiceError` on the first expression that fails to parse
    or evaluate.
    """
    errors: list[str] = []
    roll_rng = rng if rng is not None else _DICE_RNG

    def _replace(m: re.Match[str]) -> str:
        expr = (m.group(1) or m.group(2)).strip()
        try:
            result = _roll_to_text(expr, rng=roll_rng)
            verb = (
                "calculated"
                if "d" not in expr.lower()
                else "rolled"
            )
            return f"{verb} {expr}={result}"
        except Exception as e:
            errors.append(f"@roll {expr!r}: {e}")
            return m.group(0)  # leave unchanged so we can report later

    substituted = _DICE_ROLL_RE.sub(_replace, prompt)

    if errors:
        raise DiceError("; ".join(errors))

    return substituted
