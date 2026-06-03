"""Run the same stack browser e2e tests use (fake LLM + temp project + API server).

Use this when you want to **manually** open the UI that Playwright drives in
auto mode — same Lorem opening passage, ``#story`` hash, and ``testing``
dataset — without pointing ``LENS_DEV_SERVER_URL`` at your own repo.

Example::

    poe build-ui   # once, so static assets exist
    poe e2e-sandbox

Then open the printed URL (typically ``http://127.0.0.1:<port>/#story``).
Ctrl+C stops the fake LLM, server, and removes the temp project.

With a regression fixture (see ``e2e/fixtures/README.md``)::

    poe e2e-sandbox --fixture remember_section

Slow streams for cancel/skip UI testing (mock LLM defaults)::

    poe e2e-sandbox --fixture remember_section --tokens 80 --tps 2

Per-request overrides: put ``tokens=N`` and ``tps=Y`` in any operator prompt.

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
from typing import Callable, cast

from lens.core.project import ProjectSession
from lens.server.main import create_app
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

from lens.testing.regression_fixtures import (
    setup_auto_compress_low_threshold,
    setup_remember_section,
    setup_rpg_play_pins,
    setup_workflow_write_long,
)

_FIXTURE_SETUP: dict[str, Callable[[Path, str], ProjectSession]] = {
    "auto_compress_low_threshold": setup_auto_compress_low_threshold,
    "remember_section": setup_remember_section,
    "workflow_write_long": setup_workflow_write_long,
    "rpg_play_pins": setup_rpg_play_pins,
}

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
    parser.add_argument(
        "--fixture",
        choices=sorted(_FIXTURE_SETUP),
        default=None,
        help="Apply an e2e/fixtures regression setup instead of the default Lorem project.",
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=None,
        help="Default mock LLM stream length when prompts omit tokens=N.",
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=None,
        help="Default mock LLM tokens per second when prompts omit tps=Y.",
    )
    args = parser.parse_args()

    if not _STATIC_INDEX.is_file():
        print(
            "warning: lens/server/static/index.html missing — run `poe build-ui` "
            "from the Lens repo so the SPA loads.",
            flush=True,
        )

    tmp = tempfile.mkdtemp(prefix="lens_e2e_sandbox_")
    fake = FakeLLMServer(
        default_tokens=args.tokens,
        default_tps=args.tps,
    )
    fake.start()
    project_dir = Path(tmp)
    print("Setting up temp project…", flush=True)
    try:
        with fake.fast_setup():
            if args.fixture is not None:
                session = _FIXTURE_SETUP[args.fixture](project_dir, fake.base_url)
            else:
                session = setup_test_project(project_dir, fake.base_url)
    except Exception:
        fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    slug = project_dir.name
    import tomllib

    with (project_dir / "lens.toml").open("rb") as fh:
        cfg = tomllib.load(fh)
    proj_raw = cfg.get("project")
    narrative_slug = "story"
    if isinstance(proj_raw, dict):
        narr_raw = cast(dict[str, object], proj_raw).get("narrative")
        if isinstance(narr_raw, str):
            narrative_slug = narr_raw
    app = create_app({slug: session})

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
    print(f"Open in browser: {origin}/#{slug}/{narrative_slug}", flush=True)
    if args.fixture:
        print(f"Fixture: {args.fixture} (see e2e/fixtures/README.md for SH-* checklists).", flush=True)
    else:
        print(
            "Default sandbox: narrative `story`, Lorem ipsum from the fake LLM.",
            flush=True,
        )
    if args.tokens is not None or args.tps is not None:
        est = ""
        if args.tokens and args.tps and args.tps > 0:
            est = f" (~{args.tokens / args.tps:.0f}s per default stream)"
        print(
            f"Mock LLM defaults (UI only, setup was fast): tokens={args.tokens} "
            f"tps={args.tps}{est} — or put tokens=N tps=Y in a prompt.",
            flush=True,
        )
    else:
        print(
            "Tip: add --tokens 80 --tps 2 for slow streams (cancel/skip in workflow UI).",
            flush=True,
        )
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
