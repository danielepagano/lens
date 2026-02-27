"""Edit operator: LLM-assisted rewrite of a selected line range.

``lens edit ADDRESS START_LINE END_LINE [PROMPT] [--pin/-p ID]...`` streams
LLM output as a proposed replacement for lines START_LINE..END_LINE in the
targeted node, staging a claim annotation to track the transaction.

When called again with ``--retry``:
- no PROMPT   → regenerate with the same parameters
- PROMPT given → regenerate with updated instruction
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import typer

from lens.core.address import NarrativeAddress
from lens.core.operator import ContextAwareOperator, OperatorError
from lens.core.project import ProjectSession, resolve_address

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a skilled editor. Rewrite the provided passage following the"
    " given instructions, preserving the author's voice and style."
)

INSTRUCTION_TEMPLATE = ("Revise the following passage so it flows from the current passage, "
    " and following these instructions: '{prompt}'\nPASSAGE TO REVISE:\n{target}")


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class EditOperator(ContextAwareOperator):
    name: ClassVar[str] = "edit"
    requires_id: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        return INSTRUCTION_TEMPLATE.format(
            prompt=params.get("prompt", ""),
            target=params.get("target", ""),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

app = typer.Typer(invoke_without_command=True)


@app.callback()
def edit(
    address: str = typer.Argument(..., help="Narrative node address"),
    start_line: int = typer.Argument(..., help="First line to edit (1-based, inclusive)"),
    end_line: int = typer.Argument(..., help="Last line to edit (1-based, inclusive)"),
    prompt: str | None = typer.Argument(None, help="Editing instruction"),
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
        help="Re-propose with same or updated parameters",
    ),
) -> None:
    """Rewrite a line range in a narrative node using the LLM."""
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens edit: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens edit: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens edit: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(session.git_root))
    ann_id = f"e{start_line}_{end_line}"

    try:
        asyncio.run(
            EditOperator.run_mutation(
                session=session,
                node=target_node,
                rel_path=rel_path,
                ann_id=ann_id,
                start_line=start_line,
                end_line=end_line,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
            )
        )
    except OperatorError as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"lens edit: {e}", err=True)
        raise typer.Exit(1)
