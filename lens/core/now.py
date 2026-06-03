"""@now expansion: replaces ``@now`` token with the current date and approximate hour.

The formatted result looks like::

    Wednesday, April 15, around 7pm

Rounding rule: 6:31–7:30 all map to "around 7", 7:31–8:30 map to "around 8", etc.

Timezone resolution (in priority order):

1. The ``tz_name`` argument passed directly to :func:`substitute_now`.
2. The request-scoped context variable :data:`_request_timezone` (set via
   :func:`set_request_timezone` from HTTP routes using the ``Time-Zone`` header).
3. The process's local timezone (``datetime.now().astimezone()``).

Locale is read from the project's ``lens.toml`` ``[project] locale`` field
(default ``en-US``).  The locale tag is passed to ``strftime`` for weekday and
month names so they match the configured language where the platform supports it.
"""

from __future__ import annotations

import re
import zoneinfo
from contextvars import ContextVar
from datetime import datetime, timedelta

_request_timezone: ContextVar[str | None] = ContextVar("_request_timezone", default=None)

# Matches @now at a word boundary so @nowhere isn't caught
_NOW_RE = re.compile(r"@now\b")


def set_request_timezone(tz_name: str | None) -> None:
    """Set the timezone for ``@now`` expansion in the current async context.

    Call this from HTTP route handlers after reading the ``Time-Zone`` request
    header.  The value is propagated to tasks spawned by
    ``asyncio.ensure_future`` / ``asyncio.create_task`` because they inherit a
    copy of the calling context.
    """
    _request_timezone.set(tz_name)


def _format_now(tz_name: str | None, _dt: datetime | None = None) -> str:
    """Return the current date/time as a human-readable string.

    Uses ``strftime`` for weekday and month names.  The time portion uses
    "around X am/pm" with nearest-hour rounding.

    Examples::

        Wednesday, April 15, around 7pm
        Monday, January 1, around midnight
        Friday, June 21, around noon

    *_dt* is a test-only injection point; production callers should leave it
    as ``None`` so the real wall clock is used.
    """
    if _dt is not None:
        dt = _dt
    elif tz_name:
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            dt = datetime.now(tz)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            dt = datetime.now().astimezone()
    else:
        dt = datetime.now().astimezone()

    # Round to nearest hour (e.g. 6:31–7:30 → 7)
    if dt.minute <= 30:
        rounded_dt = dt.replace(minute=0, second=0, microsecond=0)
    else:
        rounded_dt = (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    hour = rounded_dt.hour  # 0-23

    if hour == 0:
        time_str = "around midnight"
    elif hour == 12:
        time_str = "around noon"
    elif hour < 12:
        time_str = f"around {hour}am"
    else:
        time_str = f"around {hour - 12}pm"

    # strftime gives locale-aware weekday (%A) and month (%B) names
    date_str = dt.strftime("%A, %B ") + str(dt.day)
    return f"{date_str}, {time_str}"


def substitute_now(
    prompt: str,
    *,
    tz_name: str | None = None,
    locale: str = "en-US",
    _dt: datetime | None = None,
) -> str:
    """Replace all ``@now`` tokens in *prompt* with the formatted date/time.

    *tz_name* overrides any context-variable timezone.  When neither is set,
    the process's local timezone is used.  The *locale* parameter is accepted
    for forward-compatibility but formatting currently relies on the platform
    strftime locale.

    *_dt* is a test-only injection point that pins the clock to a specific
    datetime; production callers should leave it as ``None``.

    Returns *prompt* unchanged when it contains no ``@now`` tokens (fast path).
    """
    if "@now" not in prompt:
        return prompt
    resolved_tz = tz_name if tz_name is not None else _request_timezone.get()
    formatted = _format_now(resolved_tz, _dt)
    return _NOW_RE.sub(formatted, prompt)
