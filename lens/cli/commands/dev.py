"""lens dev — start the Vite dev server and Lens API (HMR)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent
_UI_DIR = _LENS_ROOT / "server" / "ui"

app = typer.Typer(
    help="Start the Vite dev server and Lens API with hot reload.",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def dev(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="API port"),
) -> None:
    """Start the Vite dev server (HMR) and Lens API for the current project."""
    import uvicorn

    from lens.core.project import discover_projects

    if not shutil.which("npm"):
        typer.echo(
            "lens: dev server requires Node.js and npm. Use 'lens serve' for the built bundle.",
            err=True,
        )
        raise typer.Exit(1)
    if not (_UI_DIR / "package.json").exists():
        typer.echo(
            "lens: dev server requires lens/server/ui. Use 'lens serve' for the built bundle.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        discover_projects(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens: {e}", err=True)
        raise typer.Exit(1)

    env = {**os.environ, "VITE_API_HOST": host, "VITE_API_PORT": str(port)}
    vite_proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=_UI_DIR,
        env=env,
    )

    def shutdown() -> None:
        vite_proc.terminate()
        try:
            vite_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            vite_proc.kill()

    typer.echo("Serving Lens App (API hot-reload enabled):")
    typer.echo("  Open: http://localhost:5173")
    typer.echo("  Press Ctrl+C to stop.")
    typer.echo("")

    try:
        uvicorn.run(
            "lens.server.main:app",
            host=host,
            port=port,
            log_level="info",
            reload=True,
            reload_dirs=[str(_LENS_ROOT)],
        )
    finally:
        shutdown()
