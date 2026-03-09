"""lens serve — build the frontend and start the Lens API server."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent
_UI_DIR = _LENS_ROOT / "server" / "ui"
_STATIC_INDEX = _LENS_ROOT / "server" / "static" / "index.html"

app = typer.Typer(help="Build the frontend and start the Lens API server.")


@app.callback(invoke_without_command=True)
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Build the frontend and serve the bundle from FastAPI (no hot-reload)."""
    import uvicorn

    from lens.core.project import ProjectSession, require_lens_context
    from lens.server.main import create_app

    if not _STATIC_INDEX.exists():
        typer.echo("Building frontend…")
        result = subprocess.run(
            "npm install --silent && npm run build",
            cwd=_UI_DIR,
            shell=True,
        )
        if result.returncode != 0:
            typer.echo("lens: frontend build failed", err=True)
            raise typer.Exit(1)
        if not _STATIC_INDEX.exists():
            typer.echo("lens: build produced no index.html", err=True)
            raise typer.Exit(1)

    git_root, project_root = require_lens_context(Path.cwd())
    session = ProjectSession(git_root, project_root)
    typer.echo(f"Serving project: {project_root}")
    typer.echo(f"  http://{host}:{port}")
    uvicorn.run(create_app(session), host=host, port=port)
