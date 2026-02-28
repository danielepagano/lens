"""Shared CLI utilities for Lens operator adapters."""

from __future__ import annotations

import sys


async def confirm_tool_call(preview: str, op_desc: str) -> bool:
    """Prompt the user to confirm a chained tool call.

    Prints the generated text so far and the pending tool call description,
    then reads a y/n answer from stdin.  Returns ``False`` on EOF (non-interactive
    environment) so that automated pipelines decline gracefully.
    """
    print(f"\n--- Generated so far ---\n{preview}\n---", file=sys.stderr)
    print(f"Tool call pending: {op_desc}", file=sys.stderr)
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except EOFError:
        return False
