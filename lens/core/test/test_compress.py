"""Tests for manual and automated compress (LLM tool + collate delegation)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lens.core.compression import Aggressiveness
from lens.core.llm import FinalPayload, ToolCall
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.collate import CollateOperator
from lens.core.operators.compress import (
    compress_arguments_to_line_range,
    run_compress,
)
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.text_select import SelectionError


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _commit_content(root: Path, node: NarrativeNode, content: str) -> None:
    node.md_path().write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "content"],
        cwd=root,
        capture_output=True,
        check=True,
    )


class TestCompressArgumentsToLineRange(unittest.TestCase):
    def test_inclusive_range(self) -> None:
        text = "alpha\nbeta\ngamma\n"
        slug, start, end = compress_arguments_to_line_range(
            text,
            {
                "id": "aside",
                "selection": {
                    "start": {"target": "beta"},
                    "end": {"target": "gamma"},
                },
            },
        )
        self.assertEqual(slug, "aside")
        self.assertEqual(start, 2)
        self.assertEqual(end, 3)

    def test_single_line(self) -> None:
        text = "only\n"
        slug, start, end = compress_arguments_to_line_range(
            text,
            {"id": "x", "selection": {"start": {"target": "only"}}},
        )
        self.assertEqual((slug, start, end), ("x", 1, 1))

    def test_invalid_slug(self) -> None:
        with self.assertRaises(ValueError):
            compress_arguments_to_line_range(
                "a\n",
                {"id": "bad id", "selection": {"start": {"target": "a"}}},
            )

    def test_ambiguous_target(self) -> None:
        text = "dup\nother\ndup\n"
        with self.assertRaises(SelectionError):
            compress_arguments_to_line_range(
                text,
                {"id": "z", "selection": {"start": {"target": "dup"}}},
            )

    def test_disk_lines_account_for_stripped_comment_rows(self) -> None:
        text = "visible1\n[ noise ]: #\nvisible2\nvisible3\n"
        slug, start, end = compress_arguments_to_line_range(
            text,
            {
                "id": "aside",
                "selection": {
                    "start": {"target": "visible2"},
                    "end": {"target": "visible3"},
                },
            },
        )
        self.assertEqual((slug, start, end), ("aside", 3, 4))


class TestRunCompress(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        _init_repo(self.tmp)
        self.root, self.narrative = _make_project(self.tmp)
        _commit_content(self.root, self.narrative, "line1\nline2\nline3\n")
        self.session = ProjectSession(self.root, self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_raises_operator_error_when_no_tool(self) -> None:
        final = FinalPayload(
            text="Nothing here matches your dinner scene.",
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with self.assertRaises(OperatorError) as ctx:
                asyncio.run(
                    run_compress(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="compress the feast",
                    )
                )
        self.assertIn("compress_collate", str(ctx.exception))
        self.assertIn("Nothing here", str(ctx.exception))

    def test_empty_prompt(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            asyncio.run(
                run_compress(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="   ",
                )
            )
        msg = str(ctx.exception).lower()
        self.assertIn("prompt", msg)
        self.assertIn("aggressiveness", msg)

    def test_delegates_to_collate_on_tool(self) -> None:
        final = FinalPayload(
            text="",
            tool_calls=[
                ToolCall(
                    id="call1",
                    name="compress_collate",
                    arguments={
                        "id": "chunk",
                        "selection": {
                            "start": {"target": "line1"},
                            "end": {"target": "line2"},
                        },
                    },
                )
            ],
            usage=None,
            interrupted=False,
        )
        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with patch.object(
                CollateOperator,
                "run_collate",
                new_callable=AsyncMock,
            ) as mock_collate:
                mock_collate.return_value = Storage(self.root)
                asyncio.run(
                    run_compress(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="first two lines",
                    )
                )
        mock_collate.assert_called_once()
        kwargs = mock_collate.call_args.kwargs
        self.assertEqual(kwargs["id"], "chunk")
        self.assertEqual(kwargs["start_line"], 1)
        self.assertEqual(kwargs["end_line"], 2)
        self.assertEqual(kwargs["session"], self.session)
        self.assertEqual(kwargs["narrative"], self.narrative)

    def test_address_override_passes_node_to_collate(self) -> None:
        narrative_dir = self.root / "narrative" / "test"
        scene_dir = narrative_dir / "scene"
        scene_dir.mkdir(parents=True)
        (scene_dir / "_node.md").write_text("solo1\nsolo2\nsolo3\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "scene"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        scene = NarrativeNode(narrative_root=narrative_dir, key_path=("scene",))
        scene_addr = str(scene.to_address())

        final = FinalPayload(
            text="",
            tool_calls=[
                ToolCall(
                    id="call1",
                    name="compress_collate",
                    arguments={
                        "id": "chunk",
                        "selection": {
                            "start": {"target": "solo1"},
                            "end": {"target": "solo2"},
                        },
                    },
                )
            ],
            usage=None,
            interrupted=False,
        )
        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with patch.object(
                CollateOperator,
                "run_collate",
                new_callable=AsyncMock,
            ) as mock_collate:
                mock_collate.return_value = Storage(self.root)
                asyncio.run(
                    run_compress(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="first two solos",
                        address="/scene",
                    )
                )
        mock_collate.assert_called_once()
        kwargs = mock_collate.call_args.kwargs
        self.assertEqual(kwargs["address_str"], scene_addr)
        self.assertEqual(kwargs["start_line"], 1)
        self.assertEqual(kwargs["end_line"], 2)

    def test_no_tool_leaves_working_tree_clean(self) -> None:
        final = FinalPayload(
            text="No matching span.",
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with self.assertRaises(OperatorError):
                asyncio.run(
                    run_compress(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="compress something",
                    )
                )
        self.assertFalse(Storage(self.root).has_pending())
        self.assertFalse(Storage(self.root).has_staged())

    def test_interrupted_returns_none_and_no_pending(self) -> None:
        final = FinalPayload(
            text="",
            tool_calls=[],
            usage=None,
            interrupted=True,
        )
        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                out = asyncio.run(
                    run_compress(
                        session=self.session,
                        narrative=self.narrative,
                        prompt="compress",
                    )
                )
        self.assertIsNone(out)
        self.assertFalse(Storage(self.root).has_pending())

    def test_success_returns_collate_storage_single_unstaged_tx(self) -> None:
        final = FinalPayload(
            text="",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="compress_collate",
                    arguments={
                        "id": "chunk",
                        "selection": {
                            "start": {"target": "line1"},
                            "end": {"target": "line2"},
                        },
                    },
                )
            ],
            usage=None,
            interrupted=False,
        )
        async def _fake_summary(*args: object, **kwargs: object) -> str:
            if kwargs.get("operator_name") == "remember":
                return ""
            return "Summary."

        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with patch(
                "lens.core.operators.session.generate_text",
                new=_fake_summary,
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    st = asyncio.run(
                        run_compress(
                            session=self.session,
                            narrative=self.narrative,
                            prompt="first two lines",
                        )
                    )
        assert isinstance(st, Storage)
        self.assertTrue(st.has_pending())
        self.assertFalse(st.has_staged())


class TestRunCompressAutoMode(unittest.TestCase):
    """Tests for the aggressiveness-based (auto) path of run_compress."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        _init_repo(self.tmp)
        self.root, self.narrative = _make_project(self.tmp)
        _commit_content(self.root, self.narrative, "line1\nline2\nline3\n")
        self.session = ProjectSession(self.root, self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_prompt_no_aggressiveness_raises(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            asyncio.run(
                run_compress(
                    session=self.session,
                    narrative=self.narrative,
                )
            )
        msg = str(ctx.exception).lower()
        self.assertIn("prompt", msg)
        self.assertIn("aggressiveness", msg)

    def test_both_prompt_and_aggressiveness_raises(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            asyncio.run(
                run_compress(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="the tavern scene",
                    aggressiveness=Aggressiveness.LOW,
                )
            )
        self.assertIn("not both", str(ctx.exception).lower())

    def test_auto_path_uses_auto_system_prompt(self) -> None:
        """When aggressiveness is set (no prompt), messages use compress.auto_system."""
        final = FinalPayload(
            text="No valid range.",
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
        captured: list[list[dict[str, object]]] = []

        # Capture the messages by wrapping collect_final_payload: it receives the
        # async generator as its first argument.  We spy on generate_stream via a
        # synchronous side_effect that records messages before returning an async gen.
        async def _empty_gen():  # type: ignore[return-value]
            return
            yield  # pragma: no cover

        def _spy_generate(messages: list[dict[str, object]], *args: object, **kwargs: object) -> object:
            captured.append(list(messages))
            return _empty_gen()

        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with patch(
                "lens.core.operators.compress.generate_stream",
                side_effect=_spy_generate,
            ):
                with self.assertRaises(OperatorError):
                    asyncio.run(
                        run_compress(
                            session=self.session,
                            narrative=self.narrative,
                            aggressiveness=Aggressiveness.HIGH,
                        )
                    )
        # The system message should come from compress.auto_system, not compress.system
        self.assertTrue(len(captured) > 0, "generate_stream was not called")
        system_msg = captured[0][0]
        self.assertEqual(system_msg["role"], "system")
        # auto_system prompt contains "automatically compress"
        self.assertIn("automatically compress", str(system_msg["content"]).lower())

    def test_auto_path_fm_last_size_written_same_transaction(self) -> None:
        """After a successful auto collate, compress.last_size lands in the front matter
        and the FM write is part of the same pending transaction (not a second one)."""
        final = FinalPayload(
            text="",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="compress_collate",
                    arguments={
                        "id": "chunk",
                        "selection": {
                            "start": {"target": "line1"},
                            "end": {"target": "line2"},
                        },
                    },
                )
            ],
            usage=None,
            interrupted=False,
        )

        async def _fake_summary(*args: object, **kwargs: object) -> str:
            if kwargs.get("operator_name") == "remember":
                return ""
            return "Summary."

        with patch(
            "lens.core.operators.compress.collect_final_payload",
            new_callable=AsyncMock,
            return_value=final,
        ):
            with patch(
                "lens.core.operators.session.generate_text",
                new=_fake_summary,
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    st = asyncio.run(
                        run_compress(
                            session=self.session,
                            narrative=self.narrative,
                            aggressiveness=Aggressiveness.LOW,
                        )
                    )

        assert isinstance(st, Storage)
        self.assertTrue(st.has_pending())
        self.assertFalse(st.has_staged())

        # last_size must appear in the node's front matter
        node_text = self.narrative.md_path().read_text(encoding="utf-8")
        self.assertIn("last_size", node_text)
