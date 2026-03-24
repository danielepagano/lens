"""Dice roll substitution for prompts.

Replaces ``@roll <expr>`` and ``@roll(<expr>)`` tokens in a prompt string
with ``rolled <result>`` before the prompt is sent to the LLM.  The dice
library (https://github.com/borntyping/python-dice) evaluates the expression.

This is a user-side convenience feature — the LLM never sees the @roll
syntax, only the resolved result.
"""

from __future__ import annotations

import re

import dice  # type: ignore[import-untyped]

# Matches either:
#   @roll(<expression>)   — parenthesised form, allows spaces in expression
#   @roll<expression>     — bare form, expression runs until whitespace
_DICE_ROLL_RE = re.compile(
    r"@roll\(([^)]+)\)"  # parenthesised: @roll(expr)
    r"|"
    r"@roll(\S+)",       # bare: @rollexpr (no space)
)


class DiceError(Exception):
    """Raised when a @roll expression cannot be evaluated."""


def _roll_to_int(expr: str) -> int:
    """Evaluate a dice expression and return the integer total."""
    raw: object = dice.roll(expr)  # type: ignore[no-untyped-call]
    # dice.roll returns a Roll (list-like) or an integer-like element
    if isinstance(raw, list):
        return sum(int(v) for v in raw)  # type: ignore[arg-type]
    return int(raw)  # type: ignore[arg-type]


def substitute_rolls(prompt: str) -> str:
    """Replace all ``@roll`` expressions in *prompt* with their results.

    Raises :class:`DiceError` on the first expression that fails to parse
    or evaluate.
    """
    errors: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        expr = (m.group(1) or m.group(2)).strip()
        try:
            result = _roll_to_int(expr)
            return f"rolled {result}"
        except Exception as e:
            errors.append(f"@roll {expr!r}: {e}")
            return m.group(0)  # leave unchanged so we can report later

    substituted = _DICE_ROLL_RE.sub(_replace, prompt)

    if errors:
        raise DiceError("; ".join(errors))

    return substituted
