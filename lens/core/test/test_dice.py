"""Tests for dice roll substitution in lens.core.dice."""

from __future__ import annotations

import random
import re

import pytest

from lens.core.dice import DiceError, substitute_rolls


def _extract_rolled_block(result: str) -> str:
    # Match `_rolled <expr>=<result>_` where <expr> may include spaces.
    # `<result>` is either a single token (e.g. "17") or a list rendered like "[1, 2]".
    m = re.search(r"_rolled (.+?=(?:\[[^\]]*\]|\S+))_", result)
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
    assert result.startswith("I _rolled ")
    assert result.endswith("_ for stealth")
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
    blocks = re.findall(r"rolled (.+?=(?:\[[^\]]*\]|\S+))", result)
    assert len(blocks) == 2
    assert blocks[0].startswith("d20=")
    assert blocks[1].startswith("d6=")
    assert 1 <= _result_int(blocks[0]) <= 20
    assert 1 <= _result_int(blocks[1]) <= 6


def test_no_roll_unchanged():
    prompt = "I sneak past the guard quietly."
    assert substitute_rolls(prompt) == prompt


def test_pure_arithmetic_uses_calculated_not_rolled():
    result = substitute_rolls("sum @roll (10+20) total")
    assert "sum _calculated 10+20=30_ total" == result
    assert "rolled" not in result


def test_custom_rng_is_used_for_dice():
    rng_a = random.Random(12345)
    rng_b = random.Random(12345)
    r1 = substitute_rolls("x @roll d100 y", rng=rng_a)
    r2 = substitute_rolls("x @roll d100 y", rng=rng_b)
    assert r1 == r2
    assert "rolled d100=" in r1


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


def test_trailing_semicolon():
    result = substitute_rolls("my attack is @roll d20+3; what happens?")
    assert "rolled d20+3=" in result
    assert "; what happens?" in result


def test_trailing_exclamation():
    result = substitute_rolls("I roll @roll d6! critical!")
    assert "rolled d6=" in result
    # First ! is excluded from expression, second ! stays as word
    assert "critical!" in result


def test_trailing_question_mark():
    result = substitute_rolls("is @roll d8+2 enough?")
    assert "rolled d8+2=" in result
    assert " enough?" in result


def test_trailing_colon():
    result = substitute_rolls("damage: @roll 2d6+3: total")
    assert "rolled 2d6+3=" in result
    assert ": total" in result


def test_trailing_comma():
    result = substitute_rolls("I roll @roll d6, then move")
    assert "rolled d6=" in result
    assert ", then move" in result


def test_adjacent_punctuation():
    result = substitute_rolls("hit: @roll d20; miss: @roll d4")
    blocks = re.findall(r"rolled (.+?=(?:\[[^\]]*\]|\S+))", result)
    assert len(blocks) == 2


def test_parenthetical_aside():
    result = substitute_rolls("I check what the vibe is (insight @roll 2d20h+2)")
    assert "rolled 2d20h+2=" in result


def test_trailing_period():
    result = substitute_rolls("I rolled @roll d20.")
    assert "rolled d20=" in result
    assert result.endswith("_.")
