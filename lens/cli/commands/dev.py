"""lens dev — start the Vite dev server and Lens API (HMR)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import typer

_LENS_ROOT = Path(__file__).resolve().parent.parent.parent
_UI_DIR = _LENS_ROOT / "server" / "ui"

app = typer.Typer(help="Start the Vite dev server and Lens API with hot reload.")


@app.callback(invoke_without_command=True)
def dev(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="API port"),
) -> None:
    """Start the Vite dev server (HMR) and Lens API for the current project."""
    import uvicorn

    from lens.core.project import ProjectSession, require_lens_context
    from lens.server.main import create_app

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

    git_root, project_root = require_lens_context(Path.cwd())
    session = ProjectSession(git_root, project_root)
    app_instance = create_app(session)

    config = uvicorn.Config(app_instance, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        typer.echo("lens: uvicorn did not start in time", err=True)
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
        server.should_exit = True
        thread.join(timeout=5)

    def on_signal(signum: int, frame: object) -> None:
        shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    typer.echo(f"Serving project: {project_root}")
    typer.echo("")
    typer.echo("  Open this URL for the app (HMR enabled):")
    typer.echo("    http://localhost:5173")
    typer.echo("")
    typer.echo("  Press Ctrl+C to stop.")

    vite_proc.wait()
    shutdown()
