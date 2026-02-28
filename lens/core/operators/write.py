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
from typing import Any, ClassVar

import typer

from lens.core.operator import ContextAwareOperator, OperatorError, OperatorToolDef
from lens.core.project import ProjectSession

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
# Tool registration
# ---------------------------------------------------------------------------

WriteOperator.register_as_tool(
    OperatorToolDef(
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Writing direction or instruction for the narrative continuation",
                },
            },
        },
        prompt_snippet=(
            "Use the 'write' tool to continue open narrative — when you need to narrate "
            "consequences of player actions, describe the world, or advance story events "
            "without stopping for player decisions. Provide 'prompt' to guide what to write."
        ),
        keep_text=True,
        close_current=True,
    )
)


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
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens write: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens write: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    try:
        asyncio.run(
            WriteOperator.run_inline(
                session=session,
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
