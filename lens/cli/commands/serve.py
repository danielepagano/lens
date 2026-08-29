"""lens serve — build the frontend and start the Lens API server."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from lens.cli.help_strings import CMD_SERVE, HELP_OPTS, MEDIA_SERVER_HOST, MEDIA_SERVER_PORT

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent
_UI_DIR = _LENS_ROOT / "server" / "ui"
_STATIC_INDEX = _LENS_ROOT / "server" / "static" / "index.html"

help_panel = "Serving & deploy"

app = typer.Typer(
    help=CMD_SERVE,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(invoke_without_command=True)
def serve(
    host: str = typer.Option("127.0.0.1", help=MEDIA_SERVER_HOST),
    port: int = typer.Option(8000, help=MEDIA_SERVER_PORT),
) -> None:
    """Build the frontend and serve the bundle from FastAPI (no hot-reload)."""
    import uvicorn

    from lens.core.project import ProjectSession, discover_projects, require_cloud_compatible_mount
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

    try:
        projects = discover_projects(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens: {e}", err=True)
        raise typer.Exit(1)

    from lens.core.exceptions import LensException

    for slug, _git_root, proj in projects:
        try:
            require_cloud_compatible_mount(proj)
        except LensException as e:
            typer.echo(f"lens: project '{slug}': {e}", err=True)
            raise typer.Exit(1)

    sessions = {slug: ProjectSession(git_root, proj) for slug, git_root, proj in projects}
    for slug, _, proj in projects:
        typer.echo(f"Serving project: {slug} ({proj})")
    typer.echo(f"  http://{host}:{port}")
    uvicorn.run(create_app(sessions), host=host, port=port)
