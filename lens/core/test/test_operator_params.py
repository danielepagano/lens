"""Tests for :mod:`lens.core.operator_params`."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode
from lens.core.operator_params import (
    apply_pinned_invocation,
    chat_invocation_uses_session,
    collect_merged_raw,
    load_params_toml,
    normalize_pinned_values,
    prepare_chat_invocation,
)
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _make_narrative(root: Path, slug: str) -> NarrativeNode:
    nroot = root / "narrative" / slug
    nroot.mkdir(parents=True)
    (nroot / "_node.md").write_text("# root\n", encoding="utf-8")
    return NarrativeNode(narrative_root=nroot, key_path=())


class TestOperatorParams(unittest.TestCase):
    def test_load_params_toml_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_params_toml(root), {})

    def test_precedence_toml_then_node_child_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            slug = "story"
            (root / "lens.toml").write_text(
                '[project]\nnarrative = "story"\n\n'
                '[params.global]\nllm_id = "from-global"\n\n'
                '[params.write]\nllm_id = "from-toml-write"\n',
                encoding="utf-8",
            )
            node = _make_narrative(root, slug)
            (node.narrative_root / "ch").mkdir()
            (node.narrative_root / "ch" / "_node.md").write_text(
                "[\n  params:\n    global:\n      llm_id: parent-llm\n"
                "    write:\n      reasoning: medium\n]: #\n\n# ch\n",
                encoding="utf-8",
            )
            child = NarrativeNode(
                narrative_root=node.narrative_root, key_path=("ch",)
            )
            raw = collect_merged_raw(root, child, "write")
            self.assertEqual(raw.get("llm_id"), "parent-llm")
            self.assertEqual(raw.get("reasoning"), "medium")
            norm = normalize_pinned_values(raw)
            self.assertEqual(norm.get("llm_id"), "parent-llm")
            self.assertEqual(norm.get("reasoning"), "medium")

    def test_apply_overlay_caller_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            slug = "story"
            (root / "lens.toml").write_text(
                f'[project]\nnarrative = "{slug}"\n\n'
                '[params.write]\nllm_id = "pinned"\n',
                encoding="utf-8",
            )
            node = _make_narrative(root, slug)
            llm, reasoning, extra = apply_pinned_invocation(
                slug="write",
                project_root=root,
                focus_node=node,
                narrative=None,
                llm_id="cli",
                reasoning=None,
                extra_params=None,
            )
            self.assertEqual(llm, "cli")
            self.assertIsNone(reasoning)
            self.assertEqual(extra, {})

    def test_chat_strip_as_when_active_session_and_caller_omits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            slug = "story"
            (root / "lens.toml").write_text(
                f'[project]\nnarrative = "{slug}"\n', encoding="utf-8"
            )
            node = _make_narrative(root, slug)
            (node.narrative_root / "chat-sess").mkdir()
            (node.narrative_root / "chat-sess" / "_node.md").write_text(
                "# session\n", encoding="utf-8"
            )
            parent_md = node.narrative_root / "_node.md"
            parent_md.write_text(
                "[\n  params:\n    chat:\n      as_kb_id: npc.pinned\n"
                "      with_kb_id: pc.pinned\n]: #\n\n# root\n\n"
                "[chat:chat-sess\n  as_kb_id: npc.session\n  with_kb_id: pc.session\n]: #\n",
                encoding="utf-8",
            )
            narrative = NarrativeNode(
                narrative_root=node.narrative_root, key_path=()
            )
            focus = narrative.find_cursor()
            self.assertEqual(focus.key_path, ("chat-sess",))
            llm, reasoning, extra = apply_pinned_invocation(
                slug="chat",
                project_root=root,
                focus_node=focus,
                narrative=narrative,
                llm_id=None,
                reasoning=None,
                extra_params={},
            )
            self.assertIsNone(llm)
            self.assertIsNone(reasoning)
            self.assertNotIn("as_kb_id", extra)
            self.assertNotIn("with_kb_id", extra)

            sn, _ = ChatOperator.find_active_session(narrative)
            self.assertIsNotNone(sn)

    def test_normalize_passes_canonical_keys(self) -> None:
        raw = {"as_kb_id": "npc.direct", "llm_id": "m1"}
        norm = normalize_pinned_values(raw)
        self.assertEqual(norm.get("as_kb_id"), "npc.direct")
        self.assertEqual(norm.get("llm_id"), "m1")

    def test_normalize_preserves_false_boolean(self) -> None:
        norm = normalize_pinned_values({"wait": False})
        self.assertIs(norm.get("wait"), False)

    def test_prepare_chat_invocation_merges_as_kb_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            slug = "story"
            (root / "lens.toml").write_text(
                f'[project]\nnarrative = "{slug}"\n', encoding="utf-8"
            )
            node = _make_narrative(root, slug)
            node.md_path().write_text(
                "[\n  params:\n    chat:\n      as_kb_id: npc.from-fm\n]: #\n\n# x\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "m"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            session = ProjectSession(root, root)
            narrative = session.active_narrative
            assert narrative is not None
            *_, extra = prepare_chat_invocation(
                session,
                narrative,
                llm_id=None,
                reasoning=None,
                extra_params={},
            )
            self.assertEqual(extra.get("as_kb_id"), "npc.from-fm")

    def test_chat_session_routing_uses_pinned_with_kb_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            slug = "story"
            (root / "lens.toml").write_text(
                f'[project]\nnarrative = "{slug}"\n', encoding="utf-8"
            )
            node = _make_narrative(root, slug)
            node.md_path().write_text(
                "[\n  params:\n    chat:\n"
                "      as_kb_id: companion.agent\n"
                "      with_kb_id: human.me\n]: #\n\n# x\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "m"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            session = ProjectSession(root, root)
            narrative = session.active_narrative
            assert narrative is not None
            *_, extra = prepare_chat_invocation(
                session,
                narrative,
                llm_id=None,
                reasoning=None,
                extra_params={},
            )
            self.assertEqual(extra.get("as_kb_id"), "companion.agent")
            self.assertEqual(extra.get("with_kb_id"), "human.me")
            self.assertTrue(chat_invocation_uses_session(end=False, extra_params=extra))


if __name__ == "__main__":
    unittest.main()
