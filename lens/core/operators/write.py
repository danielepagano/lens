"""Write operator: generate narrative text at the cursor node.

``lens write [PROMPT]`` streams LLM output into the cursor node and stdout,
creating a ``[write ... ]: #`` annotation that records the configuration.

When called again while owning a pending transaction:
- no arguments  → continue, appending new content to existing
- ``--retry``   → discard generated text and regenerate with same config
- prompt/pins   → discard and regenerate with updated config
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import typer

from lens.core.operator import ContextAwareOperator, OperatorError
from lens.core.project import get_active_narrative, require_lens_context

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    'You are a creative and immersive story-writing assistant. Write in a fluent manner,'
    ' at highest reading level, never hurried, using realistic dialog and lingering on'
    ' descriptions and senses. The following sections may be provided to help you write'
    ' accurately: "RELEVANT KNOWLEDGE": leverage but not needlessly repeat facts from'
    ' these; "PREVIOUS EVENTS SUMMARY": use for orientation, but note they are summaries,'
    ' and you should write at a higher level of detail; "CURRENT PASSAGE": seamlessly'
    ' continue writing this passage if provided, using the same style and level of detail.'
)

INSTRUCTION_CONTINUE = "Continue writing."

INSTRUCTION_WITH_PROMPT = (
    "Continue writing carefully following these instructions: {prompt}."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class WriteOperator(ContextAwareOperator):
    name: ClassVar[str] = "write"
    requires_id: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        return INSTRUCTION_WITH_PROMPT.format(prompt=prompt) if prompt else INSTRUCTION_CONTINUE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

app = typer.Typer(invoke_without_command=True)


@app.callback()
def write(
    prompt: str | None = typer.Argument(
        None,
        help="Writing direction/instruction",
    ),
    pin: list[str] = typer.Option(
        [],
        "--pin",
        "-p",
        help="KB ID to pin for this operator (repeatable)",
    ),
    unpin: list[str] = typer.Option(
        [],
        "--unpin",
        "-u",
        help="KB ID to unpin for this operator (repeatable)",
    ),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help="Discard generated text and regenerate",
    ),
) -> None:
    """Generate narrative text at the cursor."""
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)

    narrative = get_active_narrative(project_root)
    if narrative is None:
        typer.echo(
            "lens write: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    try:
        asyncio.run(
            WriteOperator.run_inline(
                git_root=git_root,
                project_root=project_root,
                narrative=narrative,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
            )
        )
    except OperatorError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)
