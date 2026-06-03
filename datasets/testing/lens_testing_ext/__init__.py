"""Minimal dataset extension for Lens unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from lens.core.command_tools import CommandToolDef, register_command_tool
from lens.core.dataset_extensions import register_extension_command
from lens.core.prompts import get_prompt_text, register_prompt_spec, tool_prompt_key

app = typer.Typer(no_args_is_help=True, help="Testing dataset extension", add_completion=False)


@app.command("ping")
def ping() -> None:
    """No-op command used by extension discovery tests."""
    typer.echo("pong")


async def _testing_tool(args: dict[str, Any], project_root: Path) -> str:
    _ = args, project_root
    return "testing-ext-ok"


def register(
    *,
    dataset_name: str,
    dataset_path: Path,
    project_root: Path | None,
) -> None:
    register_extension_command("testing-ext", app)
    key = tool_prompt_key("testing_ext")
    register_prompt_spec(key, frozenset())
    description = get_prompt_text(key, project_root=project_root, dataset_path=dataset_path)
    register_command_tool(
        "testing_ext",
        CommandToolDef(
            description=description,
            parameters={
                "type": "object",
                "properties": {},
            },
            limited_to_datasets=[dataset_name],
        ),
        _testing_tool,
    )
