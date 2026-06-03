#!/usr/bin/env python3
"""Run the controllable mock LLM for bench and manual UI testing.

Use with the ``llm_mock`` profile in ``bench/llm_profiles/``::

    poe mock-llm
    # In another terminal:
    PROJECT=$(python bench/tools/setup_bench.py --profile llm_mock --scenario …)

Stream speed is controlled per request via message text::

    tokens=120 tps=4

or via this server's defaults (flags below).
"""

from __future__ import annotations

import argparse
import signal
import threading

from lens.testing.fake_llm import MOCK_LLM_DEFAULT_PORT, FakeLLMServer


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAI-compatible mock LLM with tokens=/tps= stream controls.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=MOCK_LLM_DEFAULT_PORT,
        help=f"HTTP port (default: {MOCK_LLM_DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=80,
        help="Default token count when the prompt omits tokens=N (default: 80).",
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=4.0,
        help="Default tokens per second when the prompt omits tps=Y (default: 4).",
    )
    args = parser.parse_args()

    server = FakeLLMServer(
        host=args.host,
        port=args.port,
        default_tokens=args.tokens,
        default_tps=args.tps,
    )
    server.start()
    print(f"Mock LLM listening at {server.base_url}/v1", flush=True)
    print(
        "Per-request: add tokens=N and/or tps=Y to any message "
        "(overrides these defaults).",
        flush=True,
    )
    print(f"Defaults: tokens={args.tokens} tps={args.tps}", flush=True)
    print("Ctrl+C to stop.", flush=True)

    stop = threading.Event()

    def _shutdown(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    stop.wait()
    server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
