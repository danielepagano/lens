"""Tests for dice roll substitution in lens.core.dice."""

from __future__ import annotations

import re

import pytest

from lens.core.dice import DiceError, substitute_rolls


def _extract_rolled_payload(result: str) -> str:
    m = re.search(r"\(rolled ([^)]+)\)", result)
    assert m is not None
    return m.group(1)


def _extract_ints(value: str) -> list[int]:
    return [int(n) for n in re.findall(r"-?\d+", value)]


def test_bare_roll_replaced():
    result = substitute_rolls("I @roll d20 for stealth")
    assert result.startswith("I (rolled ")
    assert result.endswith(") for stealth")
    payload = _extract_rolled_payload(result)
    ints = _extract_ints(payload)
    assert ints
    n = ints[-1]
    assert 1 <= n <= 20


def test_bare_roll_with_modifier():
    result = substitute_rolls("attack: @roll d20+5")
    m = re.search(r"rolled (\d+)", result)
    assert m is not None
    n = int(m.group(1))
    assert 6 <= n <= 25


def test_paren_roll_allows_spaces():
    result = substitute_rolls("I @roll (2d6 + 3) damage")
    m = re.search(r"rolled (\d+)", result)
    assert m is not None
    n = int(m.group(1))
    assert 5 <= n <= 15



def test_multiple_rolls_in_prompt():
    result = substitute_rolls("@roll d20 to hit, @roll d6 damage")
    payloads = re.findall(r"\(rolled ([^)]+)\)", result)
    assert len(payloads) == 2
    first_roll_ints = _extract_ints(payloads[0])
    second_roll_ints = _extract_ints(payloads[1])
    assert first_roll_ints
    assert second_roll_ints
    assert 1 <= first_roll_ints[-1] <= 20
    assert 1 <= second_roll_ints[-1] <= 6


def test_no_roll_unchanged():
    prompt = "I sneak past the guard quietly."
    assert substitute_rolls(prompt) == prompt


def test_invalid_expression_raises_dice_error():
    with pytest.raises(DiceError, match="@roll"):
        substitute_rolls("I @roll XYZZY the dragon")


def test_error_message_contains_expression():
    with pytest.raises(DiceError) as exc_info:
        substitute_rolls("roll @roll (bad!expr)")
    assert "bad!expr" in str(exc_info.value)


def test_paren_roll_keeps_trailing_text():
    result = substitute_rolls("I @roll (1d6) fire damage to the troll")
    assert "fire damage to the troll" in result
    payload = _extract_rolled_payload(result)
    ints = _extract_ints(payload)
    assert ints
    assert 1 <= ints[-1] <= 6


def test_no_space_no_match():
    # Old bare syntax @rollXYZ (no space) no longer matches — unchanged
    prompt = "I @rolld20 for stealth"
    assert substitute_rolls(prompt) == prompt


def test_empty_prompt_unchanged():
    assert substitute_rolls("") == ""
