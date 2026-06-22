from __future__ import annotations

from pathlib import Path

import typer

from lens.cli.help_strings import (
    ARG_PROMPT_KEY,
    ARG_PROMPT_CONTENT,
    ARG_PACK_NAME,
    CMD_PROMPT,
    HELP_OPTS,
)
from lens.core.commands.prompt import (
    builtin_prompts_path,
    prompt_clear,
    prompt_get,
    prompt_list,
    prompt_pack_get,
    prompt_pack_set,
    prompt_packs,
    prompt_path,
    prompt_set,
)
from lens.core.exceptions import LensException

app = typer.Typer(
    no_args_is_help=True,
    help=CMD_PROMPT,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.command("list")
def list_prompts(
    operator: str | None = typer.Option(None, "--operator", "-o", help="Filter by operator/group prefix"),
) -> None:
    """List available prompt keys."""
    try:
        keys = prompt_list(operator=operator)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    for key in keys:
        typer.echo(key)


@app.command("get", no_args_is_help=True)
def get_prompt(
    key: str = typer.Argument(..., help=ARG_PROMPT_KEY),
) -> None:
    """Print the effective prompt and its source layer."""
    try:
        record = prompt_get(key)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"# source: {record.source}")
    typer.echo(record.value)


@app.command("set", no_args_is_help=True)
def set_prompt(
    key: str = typer.Argument(..., help=ARG_PROMPT_KEY),
    content: str = typer.Argument(..., help=ARG_PROMPT_CONTENT),
) -> None:
    """Set or update a project-local prompt override."""
    try:
        path = prompt_set(key, content)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Updated project override in {path}")


@app.command("clear", no_args_is_help=True)
def clear_prompt(
    key: str = typer.Argument(..., help=ARG_PROMPT_KEY),
) -> None:
    """Remove a project-local prompt override."""
    try:
        path = prompt_clear(key)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Cleared project override in {path}")


@app.command("path")
def show_path(
    builtin: bool = typer.Option(False, "--builtin", help="Show builtin prompts file path"),
) -> None:
    """Print prompt file path for project or builtin prompts."""
    path: Path = builtin_prompts_path() if builtin else prompt_path()
    typer.echo(str(path))


@app.command("packs")
def list_packs() -> None:
    """List available prompt packs and current selection."""
    packs = prompt_packs()
    selected = prompt_pack_get()
    for pack in packs:
        marker = "*" if selected == pack else " "
        typer.echo(f"{marker} {pack}")


@app.command("use-pack")
def use_pack(
    name: str = typer.Argument(..., help=ARG_PACK_NAME),
) -> None:
    """Select a prompt pack in lens.toml."""
    try:
        prompt_pack_set(name)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Selected prompt pack: {name}")


@app.command("clear-pack")
def clear_pack() -> None:
    """Clear the selected prompt pack in lens.toml."""
    try:
        prompt_pack_set(None)
    except LensException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo("Cleared selected prompt pack")
