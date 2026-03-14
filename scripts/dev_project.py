#!/usr/bin/env python3
"""Start a self-contained Lens development environment with hot-reload.

This script:
1. Creates (or reuses) a Lens project at ``.dev-project/`` in the repo root.
2. Starts an in-process fake LLM server that streams Lorem Ipsum.
3. Starts the Vite dev server (frontend HMR on http://localhost:5173).
4. Starts the Lens API server (uvicorn --reload) bound to localhost.
5. Prints all relevant URLs so you (or an LLM) can test the CLI and API.
6. Runs until you press Ctrl-C.

Usage::

    # From the repo root:
    python scripts/dev_project.py

    # Or via poe:
    poe dev

Hot-reload
----------
- **Python** changes (``lens/`` package) are picked up automatically by
  uvicorn's file watcher — no restart needed.
- **Frontend** changes (``lens/server/ui/src/``) are picked up by Vite HMR
  — the browser updates instantly.

Use the Vite URL (port 5173) in the browser during development; it proxies
all API calls to the uvicorn server.

CLI testing
-----------
``cd`` into the printed project path, then run ``lens <command>`` normally.
The project already has:
  - narrative ``story`` as the active narrative
  - KB objects: ``person.amy``, ``place.forest``
  - ``person.amy`` pinned to the root node
  - An opening passage written by the fake LLM
  - Dataset ``testing`` enabled (provides ``person.hero``, ``place.dungeon``)

Re-running this script
----------------------
If ``.dev-project/lens.toml`` already exists the project is reused as-is.
Delete ``.dev-project/`` to start fresh.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure the repo root is on the path so we can import lens.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from lens.testing.fake_llm import FakeLLMServer  # noqa: E402
from lens.testing.project import setup_test_project  # noqa: E402

_PROJECT_DIR = _REPO_ROOT / ".dev-project"
_UI_DIR = _REPO_ROOT / "lens" / "server" / "ui"
_DEFAULT_PORT = 8000


def _ensure_project(project_dir: Path, llm_base_url: str) -> None:
    """Create the dev project if it does not already exist."""
    if (project_dir / "lens.toml").exists():
        print(f"[dev] Reusing existing project at {project_dir}")
        return

    print(f"[dev] Creating dev project at {project_dir} …")
    project_dir.mkdir(parents=True, exist_ok=True)
    setup_test_project(project_dir, llm_base_url)
    print("[dev] Project created.")


def _start_vite() -> subprocess.Popen[bytes] | None:
    """Start the Vite dev server as a subprocess. Returns None if npm is unavailable."""
    npm = shutil.which("npm")
    if npm is None:
        print("[dev] npm not found — skipping Vite dev server (frontend won't hot-reload).")
        return None
    proc = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=_UI_DIR,
    )
    return proc


def main() -> None:
    port = int(os.environ.get("LENS_DEV_PORT", _DEFAULT_PORT))

    # --- fake LLM (daemon thread — survives uvicorn reload worker restarts) ---
    llm = FakeLLMServer()
    llm.start()
    print(f"[dev] Fake LLM server:  {llm.base_url}")

    # --- dev project ---
    _ensure_project(_PROJECT_DIR, llm.base_url)

    # If the project already existed, its lens.toml may point at a stale LLM
    # URL (different port from last run).  Patch it now.
    _patch_llm_url(_PROJECT_DIR, llm.base_url)

    # --- Vite dev server ---
    vite_proc = _start_vite()

    # Change to the project directory so the _LazyApp (used by uvicorn --reload
    # worker processes) can discover the project via Path.cwd().
    os.chdir(_PROJECT_DIR)

    api_url = f"http://127.0.0.1:{port}"
    ui_url = "http://localhost:5173"

    print()
    print("=" * 60)
    print("  Lens dev environment is running  (hot-reload enabled)")
    print("=" * 60)
    print(f"  Project dir : {_PROJECT_DIR}")
    print(f"  API server  : {api_url}  (uvicorn --reload)")
    if vite_proc is not None:
        print(f"  UI (Vite)   : {ui_url}  (HMR)")
    print(f"  Fake LLM    : {llm.base_url}")
    print()
    print("  Quick checks:")
    print(f"    curl {api_url}/health")
    print(f"    curl {api_url}/stats")
    print(f"    curl {api_url}/narrative/tree")
    print()
    print("  CLI:")
    print(f"    cd {_PROJECT_DIR}")
    print("    lens stats")
    print("    lens kb list-tags")
    print()
    print("  Press Ctrl-C to stop.")
    print("=" * 60)

    # --- uvicorn with --reload (blocks; watches lens/ for Python changes) ---
    import uvicorn

    try:
        uvicorn.run(
            "lens.server.main:app",
            host="127.0.0.1",
            port=port,
            reload=True,
            reload_dirs=[str(_REPO_ROOT / "lens")],
            log_level="info",
        )
    finally:
        print("\n[dev] Shutting down …")
        if vite_proc is not None:
            vite_proc.terminate()
        llm.stop()


def _patch_llm_url(project_dir: Path, llm_base_url: str) -> None:
    """Overwrite the [[llm]] base_url in lens.toml with the current fake LLM URL."""
    import io
    import tomllib
    import tomli_w

    lens_toml = project_dir / "lens.toml"
    if not lens_toml.exists():
        return
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    llm_list = cfg.get("llm", [])
    if isinstance(llm_list, list) and llm_list:
        for entry in llm_list:
            if isinstance(entry, dict) and entry.get("id") == "mock":
                entry["base_url"] = llm_base_url
    with io.BytesIO() as buf:
        tomli_w.dump(cfg, buf)
        lens_toml.write_bytes(buf.getvalue())


if __name__ == "__main__":
    main()
