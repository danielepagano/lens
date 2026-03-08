#!/usr/bin/env python3
"""Start a self-contained Lens development environment for testing.

This script:
1. Creates (or reuses) a Lens project at ``.dev-project/`` in the repo root.
2. Starts an in-process fake LLM server that streams Lorem Ipsum.
3. Starts the Lens API server (uvicorn) bound to localhost.
4. Prints all relevant URLs so you (or an LLM) can test the CLI and API.
5. Runs until you press Ctrl-C.

Usage::

    # From the repo root:
    python scripts/dev_project.py

    # Or via poe:
    poe dev

Playwright tests
----------------
Set the ``LENS_DEV_SERVER_URL`` environment variable to the printed API URL
and the ``LENS_DEV_PROJECT_DIR`` to the printed project path, then point
your Playwright tests at that server.

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
import signal
import sys
import threading
import time
from pathlib import Path

# Ensure the repo root is on the path so we can import lens.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from lens.testing.fake_llm import FakeLLMServer  # noqa: E402
from lens.testing.project import setup_test_project  # noqa: E402

_PROJECT_DIR = _REPO_ROOT / ".dev-project"
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


def _start_lens_server(project_dir: Path, port: int) -> None:
    """Start uvicorn serving the Lens API in a daemon thread."""
    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = ProjectSession(project_dir, project_dir)
    app = create_app(session)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread  # type: ignore[return-value]


def main() -> None:
    port = int(os.environ.get("LENS_DEV_PORT", _DEFAULT_PORT))

    # --- fake LLM ---
    llm = FakeLLMServer()
    llm.start()
    print(f"[dev] Fake LLM server:  {llm.base_url}")

    # --- dev project ---
    _ensure_project(_PROJECT_DIR, llm.base_url)

    # If the project already existed, its lens.toml may point at a stale LLM
    # URL (different port from last run).  Patch it now.
    _patch_llm_url(_PROJECT_DIR, llm.base_url)

    # --- lens API server ---
    server, thread = _start_lens_server(_PROJECT_DIR, port)
    api_url = f"http://127.0.0.1:{port}"

    # Wait for uvicorn to be ready.
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        print("[dev] ERROR: uvicorn failed to start.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  Lens dev environment is running")
    print("=" * 60)
    print(f"  Project dir : {_PROJECT_DIR}")
    print(f"  API server  : {api_url}")
    print(f"  Fake LLM    : {llm.base_url}")
    print()
    print("  Quick checks:")
    print(f"    curl {api_url}/health")
    print(f"    curl {api_url}/stats")
    print(f"    curl {api_url}/tree")
    print()
    print("  CLI:")
    print(f"    cd {_PROJECT_DIR}")
    print("    lens stats")
    print("    lens kb list-tags")
    print()
    print("  Press Ctrl-C to stop.")
    print("=" * 60)

    # Keep running until interrupted.
    try:
        signal.pause()
    except (KeyboardInterrupt, AttributeError):
        # AttributeError: signal.pause() is not available on Windows.
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    print("\n[dev] Shutting down …")
    server.should_exit = True
    thread.join(timeout=5)
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
