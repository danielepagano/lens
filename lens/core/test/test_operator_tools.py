"""Unit and integration tests for operator tools.

Covers: ToolCall, tool registry, generate_stream, _dispatch_tool_call,
PlayOperator requirements, and write↔play tool chain.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

from lens.core.llm import FinalPayload, StreamEvent, ToolCall, generate_stream
from lens.core.narrative import NarrativeNode
from lens.core.operator import Operator, OperatorError
from lens.core.tools import (
    OperatorToolDef,
    _TOOL_REGISTRY,  # pyright: ignore[reportPrivateUsage]
    get_tool_registry,
    register_operator_tool,
)
from lens.dnd.operators.play import PlayOperator
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "You are a narrator."},
    {"role": "user", "content": "Write the opening line."},
]


def _sse(*payloads: dict[str, Any]) -> list[str]:
    lines = [f"data: {json.dumps(p)}" for p in payloads]
    lines.append("data: [DONE]")
    return lines


def _text_chunk(content: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": content}, "finish_reason": None}]}


def _tool_chunk_first(
    tool_id: str, name: str, args_fragment: str, finish_reason: str | None = None
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_id,
                            "function": {"name": name, "arguments": args_fragment},
                        }
                    ]
                },
                "finish_reason": finish_reason,
            }
        ]
    }


def _tool_chunk_cont(args_fragment: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": args_fragment}}]
                },
                "finish_reason": None,
            }
        ]
    }


def _finish_tool_calls() -> dict[str, Any]:
    return {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        lines: list[str] | None = None,
        body: bytes = b"",
        raise_in_iter: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body
        self._raise_in_iter = raise_in_iter

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):  # type: ignore[return]
        for line in self._lines:
            if self._raise_in_iter is not None:
                raise self._raise_in_iter
            yield line

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.captured_kwargs: dict[str, Any] = {}

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.captured_kwargs = kwargs
        return self._response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


def _fake_client_cls(response: _FakeResponse) -> tuple[Any, _FakeClient]:
    client = _FakeClient(response)

    def _factory(**_kwargs: Any) -> _FakeClient:
        return client

    return _factory, client


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True)
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _add_kb(root: Path, type_name: str, key: str, content: str = "") -> None:
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or f"{type_name}.{key}")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"kb {type_name}.{key}"], cwd=root, capture_output=True, check=True)


def _make_project(
    tmp: Path, slug: str = "test", datasets: list[str] | None = None
) -> tuple[Path, NarrativeNode]:
    project = f'[project]\nnarrative = "{slug}"\n'
    if datasets is not None:
        project += f'datasets = {json.dumps(datasets)}\n'
    project += "\n[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"test\"\n"
    (tmp / "lens.toml").write_text(project)
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True)
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


# ---------------------------------------------------------------------------
# TestOperatorToolDef
# ---------------------------------------------------------------------------


class TestOperatorToolDef(unittest.TestCase):
    def test_field_assignment(self) -> None:
        tdef = OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet="Use this tool.",
            keep_text=True,
        )
        self.assertEqual(tdef.parameters, {"type": "object", "properties": {}})
        self.assertEqual(tdef.prompt_snippet, "Use this tool.")
        self.assertTrue(tdef.keep_text)

    def test_dataclass_equality(self) -> None:
        a = OperatorToolDef(parameters={}, prompt_snippet="x", keep_text=True)
        b = OperatorToolDef(parameters={}, prompt_snippet="x", keep_text=True)
        self.assertEqual(a, b)

    def test_inequality_on_different_fields(self) -> None:
        a = OperatorToolDef(parameters={}, prompt_snippet="x", keep_text=True)
        b = OperatorToolDef(parameters={}, prompt_snippet="y", keep_text=True)
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# TestToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(_TOOL_REGISTRY)
        _TOOL_REGISTRY.clear()

    def tearDown(self) -> None:
        _TOOL_REGISTRY.clear()
        _TOOL_REGISTRY.update(self._saved)

    def _dummy_tdef(self, snippet: str = "snippet") -> OperatorToolDef:
        return OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet=snippet,
            keep_text=True,
        )

    async def _dummy_fn(self, *args: Any) -> None:
        pass

    def test_register_and_get(self) -> None:
        tdef = self._dummy_tdef()
        register_operator_tool("alpha", tdef, self._dummy_fn)
        registry = get_tool_registry()
        self.assertIn("alpha", registry)
        self.assertIs(registry["alpha"][0], tdef)

    def test_register_multiple(self) -> None:
        tdef_a = self._dummy_tdef("a")
        tdef_b = self._dummy_tdef("b")
        register_operator_tool("alpha", tdef_a, self._dummy_fn)
        register_operator_tool("beta", tdef_b, self._dummy_fn)
        registry = get_tool_registry()
        self.assertIn("alpha", registry)
        self.assertIn("beta", registry)

    def test_get_returns_snapshot(self) -> None:
        tdef = self._dummy_tdef()
        register_operator_tool("alpha", tdef, self._dummy_fn)
        snap1 = get_tool_registry()
        snap1["alpha"] = (self._dummy_tdef("mutated"), self._dummy_fn)
        snap2 = get_tool_registry()
        self.assertEqual(snap2["alpha"][0].prompt_snippet, "snippet")


# ---------------------------------------------------------------------------
# TestWritePlayRegistration
# ---------------------------------------------------------------------------


class TestWritePlayRegistration(unittest.TestCase):
    """Verify that write and play are both registered as tools."""

    def test_write_in_registry(self) -> None:
        self.assertIn("write", get_tool_registry())

    def test_play_in_registry(self) -> None:
        self.assertIn("play", get_tool_registry())

    def test_write_tool_def(self) -> None:
        tdef, _ = get_tool_registry()["write"]
        self.assertIsInstance(tdef, OperatorToolDef)
        self.assertTrue(tdef.keep_text)

    def test_play_tool_def(self) -> None:
        tdef, _ = get_tool_registry()["play"]
        self.assertIsInstance(tdef, OperatorToolDef)
        self.assertTrue(tdef.keep_text)

    def test_write_does_not_see_itself(self) -> None:
        """_do_fresh_inline filters out the current operator's name."""
        registry = get_tool_registry()
        available_for_write = {n: v for n, v in registry.items() if n != "write"}
        self.assertNotIn("write", available_for_write)
        self.assertIn("play", available_for_write)

    def test_play_does_not_see_itself(self) -> None:
        registry = get_tool_registry()
        available_for_play = {n: v for n, v in registry.items() if n != "play"}
        self.assertNotIn("play", available_for_play)
        self.assertIn("write", available_for_play)

    def test_section_in_registry(self) -> None:
        self.assertIn("section", get_tool_registry())

    def test_section_tool_def(self) -> None:
        tdef, _ = get_tool_registry()["section"]
        self.assertIsInstance(tdef, OperatorToolDef)
        self.assertTrue(tdef.keep_text)
        self.assertIn("id", tdef.parameters.get("properties", {}))
        self.assertIn("required", tdef.parameters)
        self.assertIn("id", tdef.parameters["required"])

    def test_section_tool_invoke_creates_child_with_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "location", "castle-dorn", "Castle Dorn")
            _add_kb(root, "faction", "dorn-court", "Dorn Court")
            _add_kb(root, "location", "capital-city", "Capital City")
            session = ProjectSession(git_root=root, project_root=root)
            _, invoke_fn = get_tool_registry()["section"]
            args = {
                "id": "castle-dorn",
                "kb_pin": ["location.castle-dorn", "faction.dorn-court+"],
                "kb_unpin": ["location.capital-city"],
            }
            asyncio.run(
                invoke_fn(args, session, narrative, depth=0, on_token=None, on_confirm=None)
            )
            child_md = root / "narrative" / "test" / "castle-dorn.md"
            self.assertTrue(child_md.exists())
            text = child_md.read_text()
            self.assertIn("kb_pin:", text)
            self.assertIn("location.castle-dorn", text)
            self.assertIn("faction.dorn-court+", text)
            self.assertIn("kb_unpin:", text)
            self.assertIn("location.capital-city", text)


# ---------------------------------------------------------------------------
# TestGenerateWithTools
# ---------------------------------------------------------------------------


class TestGenerateWithTools(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"test-model\"\n"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(
        self, response: _FakeResponse, **kwargs: Any
    ) -> tuple[FinalPayload | None, _FakeClient]:
        factory, client = _fake_client_cls(response)
        tools: list[dict[str, Any]] = kwargs.pop(
            "tools", [{"type": "function", "function": {"name": "play"}}]
        )
        final: FinalPayload | None = None

        async def _consume() -> None:
            nonlocal final
            async for event in generate_stream(
                MESSAGES, self.root, tools=tools if tools else None, **kwargs
            ):
                if event.final:
                    final = event.final
                    break

        with patch("lens.core.llm.httpx.AsyncClient", factory):
            asyncio.run(_consume())
        return final, client

    def test_text_only_no_tool_call(self) -> None:
        resp = _FakeResponse(
            lines=_sse(
                _text_chunk("Once"),
                _text_chunk(" upon"),
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            )
        )
        result, _ = self._run(resp)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.text, "Once upon")
        self.assertIsNone(result.tool_call)

    def test_tool_call_parsed(self) -> None:
        args_json = json.dumps({"prompt": "approach the inn"})
        resp = _FakeResponse(
            lines=_sse(
                _tool_chunk_first("call_abc", "play", args_json[:5]),
                _tool_chunk_cont(args_json[5:]),
                _finish_tool_calls(),
            )
        )
        result, _ = self._run(resp)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNotNone(result.tool_call)
        assert result.tool_call is not None
        self.assertEqual(result.tool_call.name, "play")
        self.assertEqual(result.tool_call.arguments.get("prompt"), "approach the inn")

    def test_text_plus_tool_call(self) -> None:
        args_json = json.dumps({"prompt": "face the guards"})
        resp = _FakeResponse(
            lines=_sse(
                _text_chunk("The road narrowed."),
                _tool_chunk_first("call_xyz", "play", args_json),
                _finish_tool_calls(),
            )
        )
        result, _ = self._run(resp)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.text, "The road narrowed.")
        self.assertIsNotNone(result.tool_call)

    def test_tool_call_empty_arguments(self) -> None:
        resp = _FakeResponse(
            lines=_sse(_tool_chunk_first("call_1", "play", ""), _finish_tool_calls())
        )
        result, _ = self._run(resp)
        self.assertIsNotNone(result)
        assert result is not None
        assert result.tool_call is not None
        self.assertEqual(result.tool_call.arguments, {})

    def test_tools_included_in_payload(self) -> None:
        tools = [{"type": "function", "function": {"name": "play"}}]
        resp = _FakeResponse(lines=_sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
        _, client = self._run(resp, tools=tools)
        payload = client.captured_kwargs.get("json", {})
        self.assertEqual(payload.get("tools"), tools)
        self.assertEqual(payload.get("tool_choice"), "auto")

    def test_cancel_event_stops_stream(self) -> None:
        async def _run_cancelled() -> FinalPayload | None:
            factory, _ = _fake_client_cls(
                _FakeResponse(lines=_sse(_text_chunk("x"), _text_chunk("y")))
            )
            event = asyncio.Event()
            event.set()
            final: FinalPayload | None = None
            with patch("lens.core.llm.httpx.AsyncClient", factory):
                async for ev in generate_stream(
                    MESSAGES, self.root, tools=[], cancel_event=event
                ):
                    if ev.final:
                        final = ev.final
                        break
            return final

        result = asyncio.run(_run_cancelled())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.interrupted)
        self.assertIsNone(result.tool_call)


# ---------------------------------------------------------------------------
# TestDispatchToolCall
# ---------------------------------------------------------------------------


class _WriteOpForTest(Operator):
    name: ClassVar[str] = "write"
    requires_id: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return "You are a writer."

    def build_instruction(self, params: dict[str, Any]) -> str:
        return "Continue writing."


class TestDispatchToolCall(unittest.TestCase):
    def _tdef(self, keep_text: bool = True) -> OperatorToolDef:
        return OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet="play tool",
            keep_text=keep_text,
        )

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def _make_op(self) -> MagicMock:
        op = MagicMock(spec=_WriteOpForTest)
        op.write_start = MagicMock()
        op.storage = MagicMock()
        return op

    def _dispatch(self, **overrides: Any) -> Any:
        defaults: dict[str, Any] = {
            "tool_call": ToolCall(id="1", name="play", arguments={"prompt": "x"}),
            "text": "some text",
            "cursor": MagicMock(),
            "op": self._make_op(),
            "tag": "[write]: #",
            "session": MagicMock(),
            "narrative": MagicMock(),
            "tool_def": self._tdef(),
            "invoke_fn": AsyncMock(return_value=None),
            "llm_id": None,
            "depth": 0,
            "on_token": None,
            "on_confirm": None,
            "pins": [],
            "unpins": [],
            "prompt": None,
        }
        defaults.update(overrides)
        return self._run(
            Operator._dispatch_tool_call(**defaults)  # pyright: ignore[reportPrivateUsage]
        )

    def test_keep_text_true_writes_content(self) -> None:
        op = self._make_op()
        self._dispatch(op=op, tool_call=ToolCall(id="1", name="play", arguments={"prompt": "x"}))
        op.write_start.assert_called_once()

    def test_keep_text_false_no_write(self) -> None:
        op = self._make_op()
        self._dispatch(
            op=op,
            tool_call=ToolCall(id="1", name="play", arguments={"keep_text": False}),
            tool_def=self._tdef(keep_text=True),  # arg overrides default
        )
        op.write_start.assert_not_called()

    def test_depth_zero_no_confirm(self) -> None:
        on_confirm = AsyncMock(return_value=True)
        self._dispatch(depth=0, on_confirm=on_confirm)
        on_confirm.assert_not_called()

    def test_depth_one_confirm_accept(self) -> None:
        on_confirm = AsyncMock(return_value=True)
        invoke_fn = AsyncMock(return_value=None)
        self._dispatch(depth=1, on_confirm=on_confirm, invoke_fn=invoke_fn)
        on_confirm.assert_called_once()
        invoke_fn.assert_called_once()

    def test_depth_one_confirm_decline_stops(self) -> None:
        op = self._make_op()
        on_confirm = AsyncMock(return_value=False)
        invoke_fn = AsyncMock(return_value=None)
        self._dispatch(
            op=op,
            text="keep this text",
            depth=1,
            on_confirm=on_confirm,
            invoke_fn=invoke_fn,
            tool_def=self._tdef(keep_text=True),
        )
        on_confirm.assert_called_once()
        invoke_fn.assert_not_called()
        op.write_start.assert_called_once()

    def test_depth_one_no_confirm_callback_raises(self) -> None:
        with self.assertRaises(OperatorError):
            self._dispatch(depth=1, on_confirm=None)

    def test_invoke_fn_receives_on_confirm(self) -> None:
        """invoke_fn must receive on_confirm so nested chains can propagate it."""
        on_confirm = AsyncMock(return_value=True)
        invoke_fn = AsyncMock(return_value=None)
        self._dispatch(depth=0, on_confirm=on_confirm, invoke_fn=invoke_fn)
        call_args = invoke_fn.call_args
        self.assertEqual(call_args.args[5], on_confirm)


# ---------------------------------------------------------------------------
# TestPlayOperatorRequirements
# ---------------------------------------------------------------------------


class TestPlayOperatorRequirements(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.root, self.narrative = _make_project(_init_repo(tmp))
        self.session = ProjectSession(git_root=self.root, project_root=self.root)
        self.cursor = self.narrative.find_cursor()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_pins_raises(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            PlayOperator.check_requirements(self.session, self.cursor, pins=[])
        self.assertIn("rules.dnd", str(ctx.exception))
        self.assertIn("rules.engagement", str(ctx.exception))

    def test_missing_rules_pins_raises(self) -> None:
        # Has pc.hero but missing rules pins
        with self.assertRaises(OperatorError) as ctx:
            PlayOperator.check_requirements(
                self.session, self.cursor, pins=["pc.hero"]
            )
        self.assertIn("rules.dnd", str(ctx.exception))

    def test_missing_pc_pin_raises(self) -> None:
        # Has rules pins but no pc.* pin
        with self.assertRaises(OperatorError) as ctx:
            PlayOperator.check_requirements(
                self.session, self.cursor,
                pins=["rules.dnd", "rules.engagement"],
            )
        self.assertIn("pc.", str(ctx.exception))

    def test_all_required_pins_passes(self) -> None:
        # Should not raise with rules + pc.* pins
        PlayOperator.check_requirements(
            self.session, self.cursor,
            pins=["rules.dnd", "rules.engagement", "pc.hero"],
        )

    def test_front_matter_pins_pass(self) -> None:
        # Pin all required objects via front matter, no explicit pins
        cursor_md = self.cursor.md_path()
        cursor_md.write_text(
            "[\n  kb_pin:\n  - rules.dnd\n  - rules.engagement\n  - pc.hero\n]: #\n# test\n"
        )
        PlayOperator.check_requirements(self.session, self.cursor, pins=[])


# ---------------------------------------------------------------------------
# TestMakeInvokeFn
# ---------------------------------------------------------------------------


class TestMakeInvokeFn(unittest.TestCase):
    """_make_invoke_fn returns a closure that calls cls.run_inline with depth+1."""

    def test_invoke_fn_calls_run_inline_with_incremented_depth(self) -> None:
        captured: list[int] = []

        async def _fake_run_inline(**kwargs: Any) -> None:
            captured.append(kwargs["_tool_call_depth"])

        invoke_fn = WriteOperator._make_invoke_fn()  # pyright: ignore[reportPrivateUsage]

        with patch.object(WriteOperator, "run_inline", new=_fake_run_inline):
            asyncio.run(
                invoke_fn(
                    {"prompt": "test"},
                    MagicMock(),  # session
                    MagicMock(),  # narrative
                    2,  # depth
                    None,  # on_token
                    None,  # on_confirm
                )
            )

        self.assertEqual(captured, [3])  # depth + 1


# ---------------------------------------------------------------------------
# TestRunInlineWithTools
# ---------------------------------------------------------------------------


class _ConcreteWriteOp(Operator):
    name: ClassVar[str] = "write"
    requires_id: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return "You are a writer."

    def build_instruction(self, params: dict[str, Any]) -> str:
        return "Continue writing."


class TestRunInlineWithTools(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.root, self.narrative = _make_project(_init_repo(tmp))
        self.session = ProjectSession(git_root=self.root, project_root=self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_tools_registered_uses_stream_output(self) -> None:
        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            yield StreamEvent(
                final=FinalPayload(
                    text="hello world",
                    tool_call=None,
                    usage=None,
                    interrupted=False,
                )
            )

        with patch("lens.core.operator.get_tool_registry", return_value={}):
            with patch("lens.core.operator.generate_stream", side_effect=_fake_stream):
                asyncio.run(
                    _ConcreteWriteOp.run_inline(
                        session=self.session,
                        narrative=self.narrative,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )
        cursor = self.narrative.find_cursor()
        self.assertIn("hello world", cursor.md_path().read_text())

    def test_tool_registered_uses_generate_stream(self) -> None:
        dummy_tdef = OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet="dummy tool",
            keep_text=True,
        )
        dummy_registry = {"dummy": (dummy_tdef, AsyncMock(return_value=None))}
        fake_final = FinalPayload(
            text="written content", tool_call=None, usage=None, interrupted=False
        )

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            yield StreamEvent(final=fake_final)

        with patch("lens.core.operator.get_tool_registry", return_value=dummy_registry):
            with patch(
                "lens.core.operator.generate_stream",
                side_effect=_fake_stream,
            ) as mock_gs:
                asyncio.run(
                    _ConcreteWriteOp.run_inline(
                        session=self.session,
                        narrative=self.narrative,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )
        mock_gs.assert_called_once()
        cursor = self.narrative.find_cursor()
        self.assertIn("written content", cursor.md_path().read_text())

    def test_tool_call_dispatches_invoke_fn(self) -> None:
        """When generate_stream yields a ToolCall in final, the matching invoke_fn is called."""
        invoked: list[dict[str, Any]] = []

        async def _fake_invoke(
            args: dict[str, Any],
            session: Any,
            narrative: Any,
            depth: int,
            on_token: Any,
            on_confirm: Any,
            *,
            storage: Any = None,
            llm_id: Any = None,
        ) -> None:
            invoked.append(args)

        dummy_tdef = OperatorToolDef(
            parameters={"type": "object", "properties": {}},
            prompt_snippet="dummy tool",
            keep_text=False,
        )
        dummy_registry = {"dummy": (dummy_tdef, _fake_invoke)}
        fake_final = FinalPayload(
            text="preamble",
            tool_call=ToolCall(id="c1", name="dummy", arguments={"prompt": "x"}),
            usage=None,
            interrupted=False,
        )

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            yield StreamEvent(final=fake_final)

        with patch("lens.core.operator.get_tool_registry", return_value=dummy_registry):
            with patch("lens.core.operator.generate_stream", side_effect=_fake_stream):
                asyncio.run(
                    _ConcreteWriteOp.run_inline(
                        session=self.session,
                        narrative=self.narrative,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )
        self.assertEqual(len(invoked), 1)
        self.assertEqual(invoked[0].get("prompt"), "x")


# ---------------------------------------------------------------------------
# TestWritePlayToolChain — integration test
# ---------------------------------------------------------------------------


class TestWritePlayToolChain(unittest.TestCase):
    """Integration test: write calls play via tool call, both write content."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.root, self.narrative = _make_project(
            _init_repo(tmp), datasets=PlayOperator.limited_to_datasets
        )
        self.session = ProjectSession(git_root=self.root, project_root=self.root)

        # Create a PC in the knowledge base and tag it
        from lens.core.knowledge import KnowledgeStore
        KnowledgeStore.clear_registry()
        kb_dir = self.root / "knowledge" / "person"
        kb_dir.mkdir(parents=True)
        (kb_dir / "aria.md").write_text("Aria, a ranger.\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "kb"], cwd=self.root, capture_output=True, check=True)
        kb = KnowledgeStore.for_project(self.root)
        kb.add_tags("person.aria", ["pc"])

    def tearDown(self) -> None:
        from lens.core.knowledge import KnowledgeStore
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def test_write_calls_play_tool_and_both_write(self) -> None:
        """
        Simulate: write's LLM returns a tool call for play, then play's LLM
        returns plain text.  Both pieces of content end up in the cursor node.
        """
        write_final = FinalPayload(
            text="The forest was dark and silent.",
            tool_call=ToolCall(
                id="call_1",
                name="play",
                arguments={"prompt": "approach the campfire"},
            ),
            usage=None,
            interrupted=False,
        )
        play_final = FinalPayload(
            text="Ahead you see a flickering campfire. What do you do?",
            tool_call=None,
            usage=None,
            interrupted=False,
        )

        call_count = 0

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            final = write_final if call_count == 1 else play_final
            yield StreamEvent(final=final)

        with patch("lens.core.operator.generate_stream", side_effect=_fake_stream):
            with patch.object(PlayOperator, "check_requirements"):
                asyncio.run(
                    WriteOperator.run_inline(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="describe the forest path",
                        pins=["person.aria"],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )

        cursor = self.narrative.find_cursor()
        content = cursor.md_path().read_text(encoding="utf-8")

        # Write's text was kept (keep_text=True by default)
        self.assertIn("The forest was dark and silent.", content)
        # Play's text was also written
        self.assertIn("flickering campfire", content)
        self.assertEqual(call_count, 2)

    def test_play_cannot_call_write_tool(self) -> None:
        """Play excludes write from its tools; a tool call for write is treated as unknown and play's text is written."""
        play_final = FinalPayload(
            text="You approach the gates of the city.",
            tool_call=ToolCall(
                id="call_2",
                name="write",
                arguments={"prompt": "describe the city interior"},
            ),
            usage=None,
            interrupted=False,
        )

        call_count = 0

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            yield StreamEvent(final=play_final)

        with patch("lens.core.operator.generate_stream", side_effect=_fake_stream):
            with patch.object(PlayOperator, "check_requirements"):
                asyncio.run(
                    PlayOperator.run_inline(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="arrive at the city",
                        pins=["person.aria"],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )

        cursor = self.narrative.find_cursor()
        content = cursor.md_path().read_text(encoding="utf-8")

        self.assertIn("You approach the gates", content)
        self.assertEqual(call_count, 1)

    def test_depth_one_without_confirm_raises(self) -> None:
        """A second-level tool call with no on_confirm callback raises OperatorError."""
        first_final = FinalPayload(
            text="The road continued.",
            tool_call=ToolCall(id="c1", name="play", arguments={"prompt": "x"}),
            usage=None,
            interrupted=False,
        )
        second_final = FinalPayload(
            text="Stars appeared overhead.",
            tool_call=ToolCall(
                id="c2", name="section", arguments={"id": "ch1", "prompt": "y"}
            ),
            usage=None,
            interrupted=False,
        )

        call_count = 0

        async def _fake_stream(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(final=first_final)
            else:
                yield StreamEvent(final=second_final)

        with patch("lens.core.operator.generate_stream", side_effect=_fake_stream):
            with patch.object(PlayOperator, "check_requirements"):
                with self.assertRaises(OperatorError) as ctx:
                    asyncio.run(
                        WriteOperator.run_inline(
                            session=self.session,
                            narrative=self.narrative,
                            prompt="test",
                            pins=["person.aria"],
                            unpins=[],
                            llm_id=None,
                            retry=False,
                            on_confirm=None,  # no confirm callback
                        )
                    )
        self.assertIn("on_confirm", str(ctx.exception))

    def test_run_chained_operator_invokes_target(self) -> None:
        """_run_chained_operator calls the chained operator's invoke_fn."""
        from lens.core.chain import ChainSpec

        invoked: list[dict[str, Any]] = []

        async def fake_write_invoke(
            args: dict[str, Any],
            session: Any,
            narrative: Any,
            depth: int,
            on_token: Any,
            on_confirm: Any,
            *,
            storage: Any = None,
            llm_id: Any = None,
        ) -> None:
            invoked.append(args)

        write_tdef = OperatorToolDef(
            parameters={"type": "object", "properties": {"prompt": {"type": "string"}}},
            prompt_snippet="write",
            keep_text=True,
        )
        registry = {"write": (write_tdef, fake_write_invoke)}
        chain_spec = ChainSpec(name="write", id=None, arguments={"prompt": "open the scene"})
        session = MagicMock(project_root=self.root)
        with patch("lens.core.operator.get_tool_registry", return_value=registry):
            asyncio.run(
                Operator._run_chained_operator(  # pyright: ignore[reportPrivateUsage]
                    chain_spec=chain_spec,
                    storage=MagicMock(),
                    session=session,
                    narrative=self.narrative,
                    depth=0,
                    on_token=None,
                    on_confirm=None,
                )
            )
        self.assertEqual(len(invoked), 1)
        self.assertEqual(invoked[0].get("prompt"), "open the scene")


if __name__ == "__main__":
    unittest.main()
