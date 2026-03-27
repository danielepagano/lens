"""Run the same stack browser e2e tests use (fake LLM + temp project + API server).

Use this when you want to **manually** open the UI that Playwright drives in
auto mode — same Lorem opening passage, ``#story`` hash, and ``testing``
dataset — without pointing ``LENS_DEV_SERVER_URL`` at your own repo.

Example::

    poe build-ui   # once, so static assets exist
    poe e2e-sandbox

Then open the printed URL (typically ``http://127.0.0.1:<port>/#story``).
Ctrl+C stops the fake LLM, server, and removes the temp project.

"""

from __future__ import annotations

import argparse
import shutil
import signal
import socket
import tempfile
import threading
import time
from pathlib import Path

from lens.core.project import ProjectSession
from lens.server.main import create_app
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

_STATIC_INDEX = Path(__file__).resolve().parent.parent / "server" / "static" / "index.html"


def _run() -> int:
    parser = argparse.ArgumentParser(
        description="Lens UI sandbox matching pytest e2e auto mode (temp project + fake LLM)."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for the HTTP API (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="HTTP port (0 = pick a free port).",
    )
    args = parser.parse_args()

    if not _STATIC_INDEX.is_file():
        print(
            "warning: lens/server/static/index.html missing — run `poe build-ui` "
            "from the Lens repo so the SPA loads.",
            flush=True,
        )

    tmp = tempfile.mkdtemp(prefix="lens_e2e_sandbox_")
    fake = FakeLLMServer()
    fake.start()
    try:
        setup_test_project(Path(tmp), fake.base_url)
    except Exception:
        fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    session = ProjectSession(Path(tmp), Path(tmp))
    app = create_app(session)

    with socket.socket() as s:
        s.bind((args.host, args.port))
        host, port = s.getsockname()[:2]

    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("uvicorn did not start in time")

    origin = f"http://{host}:{port}".replace("0.0.0.0", "127.0.0.1")
    print(f"Project (temp): {tmp}", flush=True)
    print(f"Open in browser: {origin}/#story", flush=True)
    print("Root narrative slug is `story`; content includes Lorem ipsum from the fake LLM.", flush=True)
    print("Ctrl+C to stop.", flush=True)

    stop = threading.Event()

    def _shutdown(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        stop.wait()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
