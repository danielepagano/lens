"""lens serve — start the Lens API server."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(invoke_without_command=True, help="Start the Lens API server.")


@app.callback()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Start the Lens API server for the current project."""
    import uvicorn

    from lens.core.project import ProjectSession, require_lens_context
    from lens.server.main import create_app

    git_root, project_root = require_lens_context(Path.cwd())
    session = ProjectSession(git_root, project_root)
    typer.echo(f"Serving project: {project_root}")
    uvicorn.run(create_app(session), host=host, port=port)
