# Testing

## Overview

Lens has three test layers, all run by `poe check`:

| Layer | Command | What it covers |
|-------|---------|----------------|
| Unit + CLI | `poe test` | Fast, no I/O — core logic, CLI parsing, D&D helpers |
| Integration | `poe test-integration` | Real git operations, storage transactions |
| E2E | `poe test-e2e` | Full stack: fake LLM → real project → CLI/API/browser |

## E2E test infrastructure

Everything under `e2e/` runs against a live, throwaway Lens project wired to
a fake LLM.  No real API key or running server is needed.

### Building blocks

**`FakeLLMServer`** (`lens/testing/fake_llm.py`)
An in-process HTTP server that speaks the OpenAI streaming SSE protocol.
Responds to any completion request with Lorem Ipsum followed by
`[input:<N>]` where N is the total character count of the messages — useful
for asserting that context assembly is wiring things up correctly.

```python
with FakeLLMServer() as llm:
    print(llm.base_url)  # http://127.0.0.1:<port>
```

**`setup_test_project()`** (`lens/testing/project.py`)
Creates a fully-populated throwaway project: git repo, `lens.toml` (pointing
at the fake LLM), KB objects (`person.amy`, `place.forest`), and an opening
passage already written by the fake LLM.  Pass `dataset="dnd"` to enable the
D&D dataset instead of the minimal testing fixtures.

```python
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

with FakeLLMServer() as llm:
    session = setup_test_project(project_dir, llm.base_url, dataset="dnd")
    # project_dir is a real git repo, ready for CLI or API calls
```

**`e2e/conftest.py`** (session fixtures)
Chains `fake_llm_server` → `lens_project_dir` → `live_server_url` (uvicorn on
a free ephemeral port).  Also exposes `base_url` for Playwright.  Set
`LENS_DEV_SERVER_URL` to bypass server setup and test against a running dev
server instead.

### Test files

**`e2e/tests/test_api_smoke.py`**
Exercises the HTTP API with plain `urllib.request` (no browser needed).
Covers `/health`, `/stats`, `/tree`, `/node/<name>`.

**`e2e/tests/test_cli.py`**
Runs `lens` subprocesses against a project with the `dnd` dataset and fake
LLM.  Covers `lens stats`, `lens kb get/with-tag`, and `lens write`.  Uses
its own module-scoped `dnd_project` fixture so it does not share state with
the API smoke tests.

**`e2e/tests/test_browser.py`**
Playwright stubs, auto-skipped when Chromium is absent.  Enable with:

```bash
playwright install chromium
```

Once a UI exists, expand these tests to assert on rendered content.

### External server mode

To run e2e tests against a persistent dev project:

```bash
poe dev  # in one terminal — starts uvicorn + watches the project
LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/
```

The conftest detects the env variable and skips spinning up its own server.
