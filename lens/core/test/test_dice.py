"""Tests for dice roll substitution in lens.core.dice."""

from __future__ import annotations

import re

import pytest

from lens.core.dice import DiceError, substitute_rolls


def _extract_rolled_block(result: str) -> str:
    m = re.search(r"\[rolled ([^\]]+)\]", result)
    assert m is not None
    return m.group(1)


def _result_int(block: str) -> int:
    assert "=" in block
    rhs = block.split("=", 1)[1].strip()
    ints = _extract_ints(rhs)
    assert ints
    return ints[-1]


def _extract_ints(value: str) -> list[int]:
    return [int(n) for n in re.findall(r"-?\d+", value)]


def test_bare_roll_replaced():
    result = substitute_rolls("I @roll d20 for stealth")
    assert result.startswith("I [rolled ")
    assert result.endswith("] for stealth")
    block = _extract_rolled_block(result)
    assert block.startswith("d20=")
    n = _result_int(block)
    assert 1 <= n <= 20


def test_bare_roll_with_modifier():
    result = substitute_rolls("attack: @roll d20+5")
    block = _extract_rolled_block(result)
    assert block.startswith("d20+5=")
    n = _result_int(block)
    assert 6 <= n <= 25


def test_paren_roll_allows_spaces():
    result = substitute_rolls("I @roll (2d6 + 3) damage")
    block = _extract_rolled_block(result)
    assert block.startswith("2d6 + 3=")
    n = _result_int(block)
    assert 5 <= n <= 15



def test_multiple_rolls_in_prompt():
    result = substitute_rolls("@roll d20 to hit, @roll d6 damage")
    blocks = re.findall(r"\[rolled ([^\]]+)\]", result)
    assert len(blocks) == 2
    assert blocks[0].startswith("d20=")
    assert blocks[1].startswith("d6=")
    assert 1 <= _result_int(blocks[0]) <= 20
    assert 1 <= _result_int(blocks[1]) <= 6


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
    block = _extract_rolled_block(result)
    assert block.startswith("1d6=")
    assert 1 <= _result_int(block) <= 6


def test_no_space_no_match():
    # Old bare syntax @rollXYZ (no space) no longer matches — unchanged
    prompt = "I @rolld20 for stealth"
    assert substitute_rolls(prompt) == prompt


def test_empty_prompt_unchanged():
    assert substitute_rolls("") == ""
