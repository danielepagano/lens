"""Helpers to create a fully-populated Lens project for testing.

The primary entry point is :func:`setup_test_project`.  It creates a git
repository, initialises a Lens project, adds a narrative, KB objects, and
a pinned character — then writes an opening passage via the write operator so
the project has real content to read and edit.

Cloud-environment safety
------------------------
``setup_test_project`` disables git commit signing for the new repo by
writing ``commit.gpgsign = false`` into its local git config.  This is safe
because the project lives in a throwaway temp directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import subprocess
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from lens.core.project import ProjectSession

_T = TypeVar("_T")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def _quiet(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def _quiet_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run *coro* in a fresh thread so it gets its own event loop.

    ``asyncio.run()`` raises if called from a thread that already has a
    running event loop (e.g. when pytest-anyio or uvicorn is active in the
    test session).  Spawning a dedicated thread avoids the conflict.
    """
    result: list[_T] = []
    exc: list[BaseException] = []

    def _run() -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                result.append(asyncio.run(coro))
            except BaseException as e:  # noqa: BLE001
                exc.append(e)

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    if exc:
        raise exc[0]
    return result[0]


def setup_test_project(
    project_dir: Path,
    llm_base_url: str,
    dataset: str = "testing",
    *,
    datasets: list[str] | None = None,
    narrative_name: str = "story",
    opening_write: bool = True,
) -> "ProjectSession":
    """Create and populate a Lens project at *project_dir*.

    Sets up:

    * A git repository (commit signing disabled for cloud compatibility)
    * ``lens.toml`` pointing at the fake LLM and the chosen dataset(s)
    * A narrative named *narrative_name* as the active narrative
    * KB objects: ``person.amy`` (protagonist), ``place.forest``
    * ``person.amy`` pinned to the root narrative node
    * An opening passage written by the fake LLM

    Returns a fresh :class:`~lens.core.project.ProjectSession` for the project.
    """
    import tomllib
    import tomli_w

    from lens.core.commands.init import init_project
    from lens.core.commands.kb import kb_add, kb_tag
    from lens.core.commands.pin import pin_add
    from lens.core.commands.use import use_narrative
    from lens.core.operators.write import WriteOperator
    from lens.core.project import ProjectSession
    from lens.core.storage import Storage

    orig_cwd = Path.cwd()
    os.chdir(project_dir)
    try:
        # --- git init ---
        _git(project_dir, "init")
        _git(project_dir, "config", "user.email", "test@lens.local")
        _git(project_dir, "config", "user.name", "Lens Test")
        # Disable commit signing for this repo (safe — throwaway dir).
        _git(project_dir, "config", "commit.gpgsign", "false")
        (project_dir / ".gitkeep").write_text("")
        _git(project_dir, "add", "-A")
        _git(project_dir, "commit", "-m", "root")

        # --- lens init + configure ---
        _quiet(init_project)
        _quiet(use_narrative, narrative_name)

        lens_toml = project_dir / "lens.toml"
        with lens_toml.open("rb") as fh:
            cfg = tomllib.load(fh)
        cfg["llm"] = [{"id": "mock", "base_url": llm_base_url, "model": "mock-model"}]
        if isinstance(cfg.get("project"), dict):
            cfg["project"]["datasets"] = list(datasets) if datasets is not None else [dataset]
        with io.BytesIO() as buf:
            tomli_w.dump(cfg, buf)
            lens_toml.write_bytes(buf.getvalue())

        Storage(project_dir).stage_all()
        _git(project_dir, "commit", "-m", "init: project setup")

        # --- knowledge base ---
        _quiet(kb_add, "person.amy", "Amy is the brave protagonist.", False)
        _quiet(kb_add, "place.forest", "A dark and ancient forest.", False)
        _quiet(kb_tag, "person.amy", ["protagonist"], [])

        session = ProjectSession(project_dir, project_dir)
        _quiet(pin_add, session, "person.amy", None, [], None)

        Storage(project_dir).stage_all()
        _git(project_dir, "commit", "-m", "kb: add initial knowledge")

        if opening_write:
            async def _write() -> None:
                narrative = session.active_narrative
                assert narrative is not None
                await WriteOperator.run_inline(
                    session=session,
                    narrative=narrative,
                    prompt="begin the story",
                    pins=[],
                    unpins=[],
                    llm_id="mock",
                    retry=False,
                )

            _quiet_async(_write())

            Storage(project_dir).stage_all()
            _git(project_dir, "commit", "-m", "write: opening passage")

        return ProjectSession(project_dir, project_dir)
    finally:
        os.chdir(orig_cwd)
