"""Tests for @now token substitution in lens.core.now."""

from __future__ import annotations

import re
import zoneinfo
from datetime import datetime

import pytest

from lens.core.now import set_request_timezone, substitute_now


_DATE_RE = re.compile(r"^\w+, \w+ \d{1,2}, .+$")

# UTC timezone used as a neutral, no-DST reference for rounding tests.
_UTC = zoneinfo.ZoneInfo("UTC")


def _dt(hour: int, minute: int = 0) -> datetime:
    """Return a UTC datetime on a fixed date for deterministic rounding tests."""
    return datetime(2026, 4, 15, hour, minute, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# Basic substitution
# ---------------------------------------------------------------------------

def test_no_at_now_unchanged() -> None:
    prompt = "The dragon roars ferociously."
    assert substitute_now(prompt) == prompt


def test_at_now_replaced() -> None:
    result = substitute_now("It is @now right now.", _dt=_dt(9))
    assert "@now" not in result
    assert "It is" in result
    assert "right now." in result


def test_multiple_at_now_all_replaced() -> None:
    result = substitute_now("@now and then @now again", _dt=_dt(9))
    assert result.count("@now") == 0
    # Both tokens expand to the same string (same call, same _dt)
    parts = result.split(" and then ")
    assert len(parts) == 2
    assert parts[0] == parts[1].replace(" again", "")


def test_at_now_word_boundary_not_matched_in_nowhere() -> None:
    prompt = "I am going @nowhere fast"
    assert substitute_now(prompt) == prompt


def test_empty_prompt_unchanged() -> None:
    assert substitute_now("") == ""


# ---------------------------------------------------------------------------
# Hour rounding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hour,minute,expected_label", [
    (0, 0, "around midnight"),
    (0, 30, "around midnight"),
    (0, 31, "around 1am"),
    (6, 30, "around 6am"),
    (6, 31, "around 7am"),
    (11, 30, "around 11am"),
    (11, 31, "around noon"),
    (12, 0, "around noon"),
    (12, 30, "around noon"),
    (12, 31, "around 1pm"),
    (23, 30, "around 11pm"),
    (23, 31, "around midnight"),
])
def test_rounding(hour: int, minute: int, expected_label: str) -> None:
    result = substitute_now("@now", _dt=_dt(hour, minute))
    assert result.endswith(expected_label), f"hour={hour}, minute={minute}: got {result!r}"


# ---------------------------------------------------------------------------
# Midnight / noon special labels
# ---------------------------------------------------------------------------

def test_midnight_label() -> None:
    result = substitute_now("@now", _dt=_dt(0, 15))
    assert "midnight" in result


def test_noon_label() -> None:
    result = substitute_now("@now", _dt=_dt(12, 0))
    assert "noon" in result


# ---------------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------------

def test_valid_timezone_used() -> None:
    """A tz_name arg adjusts the rendered hour relative to UTC."""
    # 14:00 UTC = 10:00 America/New_York (UTC-4 in summer)
    utc_dt = datetime(2026, 6, 15, 14, 0, tzinfo=_UTC)
    # Passing the tz-aware dt directly; tz_name is ignored when _dt is given
    ny_dt = utc_dt.astimezone(zoneinfo.ZoneInfo("America/New_York"))
    result = substitute_now("@now", _dt=ny_dt)
    assert "around 10am" in result


def test_invalid_timezone_falls_back_gracefully() -> None:
    """An unknown timezone string does not raise; output is still well-formed."""
    result = substitute_now("@now", tz_name="Not/AReal_Zone")
    # Fast check: still has the date pattern
    assert _DATE_RE.match(result), f"Unexpected format: {result!r}"


def test_context_var_timezone_used() -> None:
    """_request_timezone context var (set via set_request_timezone) is read when tz_name is None."""
    # 14:00 UTC = 14:00 Europe/London (UTC+1 in summer → around 3pm; but we use UTC _dt directly)
    london_dt = datetime(2026, 4, 15, 14, 0, tzinfo=zoneinfo.ZoneInfo("Europe/London"))
    set_request_timezone("Europe/London")
    try:
        result = substitute_now("@now", tz_name=None, _dt=london_dt)
        assert "around 2pm" in result
    finally:
        set_request_timezone(None)


def test_explicit_tz_name_does_not_affect_injected_dt() -> None:
    """When _dt is supplied, tz_name is superseded — the injected dt is used as-is."""
    tokyo_dt = datetime(2026, 4, 15, 10, 0, tzinfo=zoneinfo.ZoneInfo("Asia/Tokyo"))
    set_request_timezone("America/Los_Angeles")
    try:
        result = substitute_now("@now", tz_name="Asia/Tokyo", _dt=tokyo_dt)
        assert "around 10am" in result
    finally:
        set_request_timezone(None)


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

def test_output_contains_day_and_month() -> None:
    """The result matches the expected 'Weekday, Month D, around X' pattern."""
    result = substitute_now("time: @now", _dt=_dt(9))
    formatted = result.replace("time: ", "")
    assert _DATE_RE.match(formatted), f"Unexpected format: {formatted!r}"


def test_locale_param_accepted() -> None:
    """locale kwarg is accepted without error (forward-compatibility)."""
    result = substitute_now("@now", locale="fr-FR", _dt=_dt(9))
    assert "@now" not in result
