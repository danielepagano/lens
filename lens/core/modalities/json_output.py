"""Tolerant JSON parsing shared by modality refine passes.

Refine-pass LLMs are asked for strict JSON but sometimes wrap it in a markdown
fence or prepend a short preamble. Both :mod:`speech_markup` and
:mod:`media_attach` need the same tolerance, so it lives here once rather than
forked per modality.
"""

from __future__ import annotations

import json
from json import JSONDecoder
from typing import Any, cast


def strip_markdown_json_fence(text: str) -> str:
    """Remove a wrapping ``` ... ``` fence, if present; otherwise return *text* stripped."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def find_json_object(text: str) -> dict[str, Any] | None:
    """Return the first top-level JSON object in *text*, tolerating a fence or preamble.

    Strips a markdown fence, then scans for a ``{`` that starts a value which
    parses as a complete JSON object via :meth:`JSONDecoder.raw_decode`. Returns
    ``None`` if no such object is found.
    """
    stripped = strip_markdown_json_fence(text)
    decoder = JSONDecoder()
    for i, ch in enumerate(stripped):
        if ch != "{":
            continue
        try:
            data, _end = decoder.raw_decode(stripped, i)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
    return None
