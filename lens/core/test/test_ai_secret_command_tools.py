"""Regression tests for issue #74 — ``ai:secret`` leaked by design/advance.

``encode_ai_secrets`` is ROT13, an involution, so the direction of every call
site is load-bearing: storage holds encoded secrets, anything model-facing holds
decoded ones.  Encoding used to happen only on the text of one LLM round and
decoding only on the crawl graph, which left the command-tool KB paths outside
both.  Three ways plaintext reached disk:

* ``kb_get`` / ``kb_with_tag`` handed the model a KB body with the secret still
  ROT13-encoded.  When the model echoed that body back inside a ``kb`` fence —
  the normal update loop for a front — persist ROT13'd it a second time.
* ``kb_patch`` wrote its ``content`` straight to the KB with no encode step.
* A secret comment straddling a command-tool round boundary matched the encode
  regex in neither round.

Only ``design`` and ``advance`` set ``use_command_tools = True``, which is why
those two operators were the ones that leaked.
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

from lens.core.annotations import decode_ai_secrets, encode_ai_secrets
from lens.core.command_tools import kb_patch_handler
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import FinalPayload, generate_stream
from lens.core.storage import Storage

SECRET_PLAINTEXT = "the king betrayed everyone"
SECRET_ROT13 = "gur xvat orgenlrq rirelbar"

_MESSAGES = [{"role": "user", "content": "update the front"}]


def _init_project(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True,
    )
    (tmp / "lens.toml").write_text(
        '[project]\nnarrative = "test"\n\n'
        '[[llm]]\nid = "default"\nbase_url = "http://localhost:1"\nmodel = "m"\n'
    )
    (tmp / "narrative" / "test").mkdir(parents=True)
    (tmp / "narrative" / "test" / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _store_front(root: Path) -> None:
    """Store a front the way ``design``/``advance`` do: secret already ROT13-encoded."""
    storage = Storage(root)
    kb = KnowledgeStore.for_project(root, storage=storage)
    kb.store_object(
        "front.goblins",
        "Goblin bake-off\n\n"
        "- Problem: the goblins are baking\n\n"
        + encode_ai_secrets(f"<!-- ai:secret:\n{SECRET_PLAINTEXT}\n-->")
        + "\n",
    )
    storage.stage_all()


def _tool_call_delta(content: str = "") -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "content": content,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "kb_get",
                                "arguments": json.dumps({"ids": ["front.goblins"]}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _run_two_rounds(
    root: Path,
    round1: dict[str, Any],
    round2_content: "Any",
    handler: Any,
    requests: list[dict[str, Any]] | None = None,
) -> FinalPayload:
    """Drive ``generate_stream`` through one command-tool round and a final round.

    *round2_content* is a zero-arg callable so the second round can echo what the
    tool handler returned in the first.  *requests*, when given, collects each
    round's request payload so tests can assert on what the model was sent.
    """
    call_count = 0

    class _Resp:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):  # type: ignore[return]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield f"data: {json.dumps(round1)}"
            else:
                payload = {"choices": [{"delta": {"content": round2_content()}}]}
                yield f"data: {json.dumps(payload)}"
            yield "data: [DONE]"

        async def __aenter__(self) -> "_Resp":
            return self

        async def __aexit__(self, *_: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    class _Client:
        def build_request(self, _m: str, _u: str, **kw: Any) -> object:
            if requests is not None:
                requests.append(cast(dict[str, Any], kw.get("json", {})))
            return object()

        async def send(self, _req: object, *, stream: bool = False) -> _Resp:
            _ = stream
            return _Resp()

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_: Any) -> None:
            pass

    async def _inner() -> FinalPayload | None:
        final: FinalPayload | None = None
        async for event in generate_stream(
            _MESSAGES,
            root,
            command_tool_handlers={"kb_get": handler},
            operator_name="design",
        ):
            if event.final:
                final = event.final
        return final

    def _make_client(**_kw: Any) -> _Client:
        return _Client()

    with patch("lens.core.llm.httpx.AsyncClient", _make_client):
        final = asyncio.run(_inner())
    assert final is not None
    return final


class TestKbGetSecretParity(unittest.TestCase):
    """``kb_get`` must show the model the same decoded text crawl shows it."""

    def test_kb_get_decodes_secrets_like_crawl(self) -> None:
        from lens.core.command_tools import _kb_get  # pyright: ignore[reportPrivateUsage]

        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            out = asyncio.run(_kb_get({"ids": ["front.goblins"]}, root))

        self.assertIn(SECRET_PLAINTEXT, out)
        self.assertNotIn(SECRET_ROT13, out)


class TestEchoedKbGetResult(unittest.TestCase):
    """The model echoing a ``kb_get`` body into a ``kb`` fence must stay encoded."""

    def test_echoed_kb_get_result_persists_encoded(self) -> None:
        from lens.core.command_tools import _kb_get  # pyright: ignore[reportPrivateUsage]

        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            seen: dict[str, str] = {}

            async def handler(args: dict[str, Any], _root: Path) -> str:
                seen["result"] = await _kb_get(args, root)
                return seen["result"]

            def round2() -> str:
                # Drop the leading ``KB['front.goblins']`` header line; the rest is
                # the body the model copies verbatim into its update block.
                body = seen["result"].split("\n", 1)[1]
                return (
                    "Updating the front.\n\n"
                    "```kb\n---\nid: front.goblins\n---\n" + body + "\n```\n"
                )

            final = _run_two_rounds(root, _tool_call_delta(), round2, handler)

        self.assertIn(SECRET_ROT13, final.text)
        self.assertNotIn(SECRET_PLAINTEXT, final.text)


class TestSecretSplitAcrossToolRounds(unittest.TestCase):
    """A secret straddling a command-tool round boundary must still be encoded."""

    @staticmethod
    async def _handler(_args: dict[str, Any], _root: Path) -> str:
        return "some kb content"

    def _fence_head(self, opening_half: str) -> dict[str, Any]:
        return _tool_call_delta(
            "```kb\n---\nid: front.goblins\n---\nGoblin bake-off\n\n"
            f"<!-- ai:secret:\n{opening_half}"
        )

    def test_closing_marker_alone_in_second_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            final = _run_two_rounds(
                root,
                self._fence_head(SECRET_PLAINTEXT),
                lambda: "\n-->\n```\n",
                self._handler,
            )

        self.assertNotIn(SECRET_PLAINTEXT, final.text)
        self.assertIn(SECRET_ROT13, final.text)

    def test_second_round_carries_the_rest_of_the_secret(self) -> None:
        # The realistic split: the tool call interrupts mid-sentence, so the
        # closing round carries secret content of its own.  Encoding each round
        # in isolation leaves that half in plaintext — the round after the
        # boundary has no opener to match.
        head, tail = SECRET_PLAINTEXT.split(" ", 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            final = _run_two_rounds(
                root,
                self._fence_head(head),
                lambda: f" {tail}\n-->\n```\n",
                self._handler,
            )

        self.assertNotIn(tail, final.text)
        self.assertNotIn(SECRET_PLAINTEXT, final.text)
        # The tool-call fence is appended between the two halves, so the block
        # reads back as the secret with the audit fence spliced into it — both
        # decoded, neither left as ROT13.
        decoded = decode_ai_secrets(final.text)
        self.assertIn(head, decoded)
        self.assertIn(tail, decoded)
        self.assertIn("kb_get", decoded)

    def test_prose_after_the_close_is_left_alone(self) -> None:
        head, tail = SECRET_PLAINTEXT.split(" ", 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            final = _run_two_rounds(
                root,
                self._fence_head(head),
                lambda: f" {tail}\n-->\n```\n\nAnd the town is safe.\n",
                self._handler,
            )

        self.assertIn("And the town is safe.", final.text)


class TestAssistantReplayIsModelForm(unittest.TestCase):
    """Rounds replayed to their author must be decoded, or the model re-encodes them."""

    def test_assistant_turn_sent_back_decoded(self) -> None:
        async def handler(_args: dict[str, Any], _root: Path) -> str:
            return "some kb content"

        requests: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            _run_two_rounds(
                root,
                _tool_call_delta(
                    f"Noting it down.\n<!-- ai:secret:\n{SECRET_PLAINTEXT}\n-->\n"
                ),
                lambda: "Done.\n",
                handler,
                requests=requests,
            )

        assistant = [
            m
            for m in requests[-1]["messages"]
            if m.get("role") == "assistant" and m.get("content")
        ]
        self.assertTrue(assistant, "expected the first round replayed as assistant")
        content = assistant[-1]["content"]
        self.assertIn(SECRET_PLAINTEXT, content)
        self.assertNotIn(SECRET_ROT13, content)

    def test_split_assistant_turn_sent_back_decoded(self) -> None:
        head, tail = SECRET_PLAINTEXT.split(" ", 1)

        async def handler(_args: dict[str, Any], _root: Path) -> str:
            return "some kb content"

        requests: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            _store_front(root)
            _run_two_rounds(
                root,
                _tool_call_delta(f"Noting it down.\n<!-- ai:secret:\n{head}"),
                lambda: f" {tail}\n-->\n",
                handler,
                requests=requests,
            )

        content = [
            m["content"]
            for m in requests[-1]["messages"]
            if m.get("role") == "assistant" and m.get("content")
        ][-1]
        self.assertTrue(content.endswith(head), content)


class TestKbPatchSecretEncoding(unittest.TestCase):
    """``kb_patch`` content is written straight through with no encode step."""

    def test_kb_patch_content_persisted_encoded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_project(Path(tmp))
            storage = Storage(root)
            kb = KnowledgeStore.for_project(root, storage=storage)
            kb.store_object("front.goblins", "Goblin bake-off\n\nPLACEHOLDER\n")
            storage.stage_all()

            asyncio.run(
                kb_patch_handler(
                    {
                        "id": "front.goblins",
                        "patches": [
                            {
                                "start": {"target": "PLACEHOLDER"},
                                "content": f"<!-- ai:secret:\n{SECRET_PLAINTEXT}\n-->",
                            }
                        ],
                    },
                    root,
                )
            )
            stored = (root / "knowledge" / "front" / "goblins.md").read_text()

        self.assertIn(SECRET_ROT13, stored)
        self.assertNotIn(SECRET_PLAINTEXT, stored)


if __name__ == "__main__":
    unittest.main()
