"""A model-requested module latches: include above the tag, compact fence inside.

Drives a real inline generation through :func:`~lens.core.llm.generate_stream`
(fake transport, real tool loop) so the whole chain is exercised: catalog → tool
call → handler → sink → persist.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from lens.core.context import CrawlSpec, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.module_requests import (
    LOAD_MODULE_TOOL,
    clear_module_registry,
    unloaded_modules,
)
from lens.core.narrative import NarrativeNode
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession

MODULE_ID = "rules.skirmish"
MODULE_BODY = "# Skirmish\n\nRoll off, higher wins. UNIQUE_MODULE_MARKER\n"
REPLY = "Steel rings off the doorframe."

MANIFEST = f"""\
[dataset]

[[dataset.modules]]
id = "{MODULE_ID}"
operators = ["write"]
description = "Turn order and damage. Load when violence starts."
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _round(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}"


def _tool_round() -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "content": "",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": LOAD_MODULE_TOOL,
                                "arguments": json.dumps({"module": MODULE_ID}),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


class _FakeTransport:
    """Round 1 asks for the module, round 2 (and any later round) writes prose."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.rounds = 0

    def client(self, **_kw: Any) -> Any:
        transport = self

        class _Resp:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_lines(self):  # type: ignore[no-untyped-def]
                transport.rounds += 1
                if transport.rounds == 1 and transport.tool_round_wanted:
                    yield _round(_tool_round())
                else:
                    yield _round({"choices": [{"delta": {"content": REPLY}}]})
                yield "data: [DONE]"

            async def __aenter__(self) -> "_Resp":
                return self

            async def __aexit__(self, *_: Any) -> None:
                return None

            async def aclose(self) -> None:
                return None

        class _Client:
            def build_request(self, _m: str, _u: str, **kw: Any) -> object:
                transport.requests.append(cast(dict[str, Any], kw.get("json", {})))
                return object()

            async def send(self, _req: object, *, stream: bool = False) -> _Resp:
                _ = stream
                return _Resp()

            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, *_: Any) -> None:
                return None

        return _Client()

    tool_round_wanted: bool = True

    def offered_tool_names(self, request_index: int = 0) -> list[str]:
        tools = cast(
            "list[dict[str, Any]]", self.requests[request_index].get("tools") or []
        )
        return [str(t["function"]["name"]) for t in tools]


class TestModuleIncludeLatches(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "project"
        self.root.mkdir()
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "test@test.com")
        _git(self.root, "config", "user.name", "Test")

        dataset = base / "moduleset"
        (dataset / "knowledge" / "rules").mkdir(parents=True)
        (dataset / "knowledge" / "rules" / "skirmish.md").write_text(
            MODULE_BODY, encoding="utf-8"
        )
        (dataset / "lens.toml").write_text(MANIFEST, encoding="utf-8")

        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\ndatasets = ["moduleset"]\n'
            '[[llm]]\nbase_url = "http://127.0.0.1:1/v1"\nmodel = "m"\n',
            encoding="utf-8",
        )
        (self.root / "lens.local.toml").write_text(
            f'[dataset_paths]\nmoduleset = "{dataset}"\n', encoding="utf-8"
        )
        (self.root / "knowledge").mkdir()
        self.narrative_dir = self.root / "narrative" / "story"
        self.narrative_dir.mkdir(parents=True)
        (self.narrative_dir / "_node.md").write_text("Kira waits.\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "project")

        clear_module_registry()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self.narrative = NarrativeNode(narrative_root=self.narrative_dir, key_path=())
        self.transport = _FakeTransport()

    def tearDown(self) -> None:
        clear_module_registry()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def _write(self, prompt: str | None, *, retry: bool = False) -> None:
        with patch("lens.core.llm.httpx.AsyncClient", self.transport.client):
            asyncio.run(
                WriteOperator.run_inline(
                    session=ProjectSession(self.root, self.root),
                    narrative=self.narrative,
                    prompt=prompt,
                    pins=[],
                    unpins=[],
                    llm_id=None,
                    retry=retry,
                )
            )

    def _node_text(self) -> str:
        return (self.narrative_dir / "_node.md").read_text(encoding="utf-8")

    def test_include_lands_above_the_open_tag_and_nothing_else_is_written(
        self,
    ) -> None:
        self._write("they draw steel")
        text = self._node_text()

        include_line = text.index(f"[include: {MODULE_ID}]: #")
        tag_line = text.index("[write")
        self.assertLess(
            include_line,
            tag_line,
            "the include must sit outside the block so retry cannot discard it",
        )
        # The include is the whole record.  No fence: it would say nothing the
        # cursor does not show, and every later beat would read the tool name
        # back as part of the assistant turn.  No body either, obviously.
        self.assertNotIn("tool-call", text)
        self.assertNotIn(LOAD_MODULE_TOOL, text)
        self.assertNotIn("UNIQUE_MODULE_MARKER", text)
        self.assertIn(REPLY, text)

    def test_the_model_saw_the_module_in_the_same_reply(self) -> None:
        self._write("they draw steel")

        second_round = self.transport.requests[1]
        tool_results = [
            m for m in second_round["messages"] if m.get("role") == "tool"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("UNIQUE_MODULE_MARKER", tool_results[0]["content"])

    def test_offered_once_then_never_again(self) -> None:
        self._write("they draw steel")
        self.assertIn(LOAD_MODULE_TOOL, self.transport.offered_tool_names())

        # Next beat: the include is on disk, so the module is in scope and the
        # catalog is empty — no tool, and no task hint either.
        self.transport.tool_round_wanted = False
        self._write("the fight continues")

        self.assertEqual(self.transport.offered_tool_names(-1), [])
        node = NarrativeNode(narrative_root=self.narrative_dir, key_path=())
        self.assertEqual(
            unloaded_modules(self.root, "write", crawl(CrawlSpec.of(node))), ()
        )

    def test_retry_keeps_the_include_and_does_not_re_offer(self) -> None:
        self._write("they draw steel")
        self.transport.tool_round_wanted = False

        self._write(None, retry=True)

        text = self._node_text()
        self.assertEqual(text.count(f"[include: {MODULE_ID}]: #"), 1)
        self.assertLess(text.index(f"[include: {MODULE_ID}]: #"), text.index("[write"))
        self.assertEqual(self.transport.offered_tool_names(-1), [])

    def test_an_operator_without_the_tool_is_never_told_to_call_it(self) -> None:
        """The hint and the tool share one gate.

        Only operators whose generation runs through the base inline flow are
        handed a sink, so only they can be offered the tool.  A dataset targeting
        any other operator must produce silence, not a task that tells the model
        to call a tool that is not in the request — which would end as narrated
        stage directions or a phantom call persisted as a stray fence.
        """
        from lens.core.operators.chat import ChatOperator

        self.assertFalse(ChatOperator.supports_module_requests)

        node = NarrativeNode(narrative_root=self.narrative_dir, key_path=())
        crawl_result = crawl(CrawlSpec.of(node))
        storage = ProjectSession(self.root, self.root).new_storage(owner=None)
        instruction = ChatOperator(storage, node).append_module_hint(
            crawl_result, "TASK BODY"
        )

        self.assertEqual(instruction, "TASK BODY")
        # …while the operator that does get the tool still gets the hint.
        self.assertIn(
            LOAD_MODULE_TOOL,
            WriteOperator(storage, node).append_module_hint(crawl_result, "TASK BODY"),
        )

    def test_task_advertises_the_module_until_it_is_loaded(self) -> None:
        self.transport.tool_round_wanted = False
        self._write("they talk")

        first_task = self.transport.requests[0]["messages"][-1]["content"]
        self.assertIn(LOAD_MODULE_TOOL, first_task)
        self.assertIn(MODULE_ID, first_task)


if __name__ == "__main__":
    unittest.main()
