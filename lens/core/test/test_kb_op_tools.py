"""The four KB verbs: what they refuse, and what they leave behind.

A tool call is the only emit form with a return channel inside the turn, which
is the whole reason these are tools and not a fence: a call that does not
validate writes no proposal, returns its error, and the model tries again.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.kb_op_tools import (
    KB_ADD_TOOL,
    KB_OP_TOOLS,
    KB_PATCH_PROPOSAL_TOOL,
    KB_REMOVE_TOOL,
    KB_TAG_TOOL,
    build_kb_op_bundle,
    render_kb_op_persist,
)
from lens.core.kb_pending import KbOpSink, inflight_ops, parse_kb_ops
from lens.core.knowledge import KnowledgeStore


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


def _make_project(tmp: Path, datasets: list[str] | None = None) -> None:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    body = '[project]\nnarrative = "story"\n'
    if datasets:
        listed = ", ".join(f'"{name}"' for name in datasets)
        body += f"datasets = [{listed}]\n"
    (tmp / "lens.toml").write_text(body)
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    node_dir = tmp / "narrative" / "story"
    node_dir.mkdir(parents=True)
    (node_dir / "_node.md").write_text("[\n  kb_pin: []\n]: #\n\nPROLOGUE\n")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "init")


class _ToolCase(unittest.TestCase):
    datasets: list[str] = []

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root, self.datasets)
        self.store = KnowledgeStore.for_project(self.root)
        self.sink = KbOpSink()
        bundle = build_kb_op_bundle(self.sink, self.root)
        self.handlers = bundle.handlers or {}
        self.tools = bundle.tools or []
        self._scope = inflight_ops(self.root, self.sink)
        self._scope.__enter__()

    def tearDown(self) -> None:
        self._scope.__exit__(None, None, None)
        KnowledgeStore.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, name: str, **args: Any) -> str:
        async def _run() -> str:
            return await self.handlers[name](args, self.root)

        return asyncio.run(_run())


class TestKbAdd(_ToolCase):
    def test_creates_a_proposal_visible_immediately(self) -> None:
        result = self.call(KB_ADD_TOOL, id="loc.vault", body="# The Vault\n")
        self.assertTrue(result.startswith("OK:"))
        self.assertEqual(len(self.sink.ops), 1)
        self.assertIn("The Vault", self.store.get_objects(["loc.vault"])["loc.vault"].text)
        self.assertFalse((self.root / "knowledge" / "loc" / "vault.md").exists())

    def test_a_later_lookup_in_the_same_turn_sees_it(self) -> None:
        self.call(KB_ADD_TOOL, id="loc.vault", body="# The Vault\n")
        from lens.core.command_tools import _kb_get  # pyright: ignore[reportPrivateUsage]

        out = asyncio.run(_kb_get({"ids": ["loc.vault"]}, self.root))
        self.assertIn("The Vault", out)

    def test_refuses_an_id_that_already_exists(self) -> None:
        self.store.store_object("loc.vault", "already here\n")
        result = self.call(KB_ADD_TOOL, id="loc.vault", body="clobber\n")
        self.assertTrue(result.startswith("(error:"))
        self.assertIn("kb_patch", result)
        self.assertEqual(self.sink.ops, [])

    def test_replaces_its_own_earlier_proposal(self) -> None:
        self.call(KB_ADD_TOOL, id="loc.vault", body="first\n")
        result = self.call(KB_ADD_TOOL, id="loc.vault", body="second\n")
        self.assertTrue(result.startswith("OK:"))
        self.assertIn("second", self.store.get_objects(["loc.vault"])["loc.vault"].text)

    def test_refuses_a_malformed_id(self) -> None:
        self.assertTrue(self.call(KB_ADD_TOOL, id="nodot", body="x").startswith("(error:"))
        self.assertEqual(self.sink.ops, [])

    def test_refuses_a_template(self) -> None:
        result = self.call(KB_ADD_TOOL, id="loc._template", body="x")
        self.assertIn("lens kb template", result)
        self.assertEqual(self.sink.ops, [])

    def test_refuses_a_missing_body(self) -> None:
        self.assertTrue(self.call(KB_ADD_TOOL, id="loc.vault").startswith("(error:"))


class TestKbPatch(_ToolCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("loc.vault", "alpha\nbeta\n")

    def test_patches_an_existing_object(self) -> None:
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "beta"}, "content": "BETA"}],
        )
        self.assertTrue(result.startswith("OK: patched"))
        self.assertIn("BETA", self.store.get_objects(["loc.vault"])["loc.vault"].text)
        self.assertEqual((self.root / "knowledge" / "loc" / "vault.md").read_text(), "alpha\nbeta\n")

    def test_returns_the_updated_body_so_a_second_patch_can_anchor(self) -> None:
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "beta"}, "content": "BETA"}],
        )
        self.assertIn("BETA", result)

    def test_patches_compose_across_calls(self) -> None:
        self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "beta"}, "content": "BETA"}],
        )
        self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "alpha"}, "content": "ALPHA"}],
        )
        text = self.store.get_objects(["loc.vault"])["loc.vault"].text
        self.assertIn("ALPHA", text)
        self.assertIn("BETA", text)

    def test_can_patch_an_object_proposed_this_session(self) -> None:
        self.call(KB_ADD_TOOL, id="loc.crypt", body="one\ntwo\n")
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.crypt",
            patches=[{"start": {"target": "two"}, "content": "TWO"}],
        )
        self.assertTrue(result.startswith("OK:"))
        self.assertIn("TWO", self.store.get_objects(["loc.crypt"])["loc.crypt"].text)

    def test_an_unresolvable_patch_writes_no_proposal(self) -> None:
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "no such line"}, "content": "x"}],
        )
        self.assertTrue(result.startswith("(error:"))
        self.assertEqual(self.sink.ops, [])

    def test_refuses_a_missing_object(self) -> None:
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.nowhere",
            patches=[{"start": {"target": "a"}, "content": "b"}],
        )
        self.assertIn("kb_add", result)
        self.assertEqual(self.sink.ops, [])

    def test_the_end_sentinel_appends(self) -> None:
        # The modality tells the model to append with @@@end rather than repeat
        # the last line as an anchor. A real session did the latter and sent the
        # anchor twice, so this pins that the advice actually works.
        result = self.call(
            KB_PATCH_PROPOSAL_TOOL,
            id="loc.vault",
            patches=[{"start": {"target": "@@@end"}, "content": "\ngamma"}],
        )
        self.assertTrue(result.startswith("OK: patched"))
        text = self.store.get_objects(["loc.vault"])["loc.vault"].text
        self.assertTrue(text.rstrip().endswith("gamma"))
        self.assertIn("alpha", text)
        self.assertIn("beta", text)


class TestKbTag(_ToolCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("loc.vault", "body\n")

    def test_adds_and_removes(self) -> None:
        self.store.add_tags("loc.vault", ["draft"])
        result = self.call(
            KB_TAG_TOOL, id="loc.vault", tags=["sunken"], remove_tags=["draft"]
        )
        self.assertTrue(result.startswith("OK:"))
        self.assertEqual(self.store.get_tags("loc.vault"), ["sunken"])
        self.assertNotIn("sunken", (self.root / "knowledge" / "tags.toml").read_text())

    def test_refuses_a_malformed_tag(self) -> None:
        result = self.call(KB_TAG_TOOL, id="loc.vault", tags=["has spaces"])
        self.assertIn("malformed", result)
        self.assertEqual(self.sink.ops, [])

    def test_refuses_a_link_to_an_object_that_does_not_exist(self) -> None:
        result = self.call(KB_TAG_TOOL, id="loc.vault", tags=["npc.nobody"])
        self.assertIn("do not exist", result)
        self.assertEqual(self.sink.ops, [])

    def test_a_link_to_an_object_proposed_this_session_is_allowed(self) -> None:
        self.call(KB_ADD_TOOL, id="npc.vasa", body="Vasa\n")
        result = self.call(KB_TAG_TOOL, id="loc.vault", tags=["npc.vasa"])
        self.assertTrue(result.startswith("OK:"))

    def test_requires_at_least_one_direction(self) -> None:
        self.assertTrue(self.call(KB_TAG_TOOL, id="loc.vault").startswith("(error:"))

    def test_refuses_a_missing_object(self) -> None:
        result = self.call(KB_TAG_TOOL, id="loc.nowhere", tags=["x"])
        self.assertIn("nothing to tag", result)


class TestKbRemove(_ToolCase):
    datasets = ["testing"]

    def test_takes_back_something_created_this_session(self) -> None:
        self.call(KB_ADD_TOOL, id="loc.mistake", body="oops\n")
        result = self.call(KB_REMOVE_TOOL, id="loc.mistake")
        self.assertIn("Nothing was ever written", result)
        self.assertFalse(self.store.exists("loc.mistake"))

    def test_proposes_deletion_of_a_project_object(self) -> None:
        self.store.store_object("loc.vault", "body\n")
        result = self.call(KB_REMOVE_TOOL, id="loc.vault")
        self.assertTrue(result.startswith("OK: removing"))
        self.assertFalse(self.store.exists("loc.vault"))
        self.assertTrue((self.root / "knowledge" / "loc" / "vault.md").exists())

    def test_refuses_a_dataset_only_object(self) -> None:
        result = self.call(KB_REMOVE_TOOL, id="person.hero")
        self.assertIn("dataset:testing", result)
        self.assertIn("read-only", result)
        self.assertEqual(self.sink.ops, [])

    def test_removing_a_fork_says_the_dataset_comes_back(self) -> None:
        self.store.store_object("person.hero", "a project fork\n")
        result = self.call(KB_REMOVE_TOOL, id="person.hero")
        self.assertIn("project copy", result)
        self.assertIn("dataset:testing will resolve again", result)

    def test_refuses_an_object_that_does_not_exist(self) -> None:
        result = self.call(KB_REMOVE_TOOL, id="loc.nowhere")
        self.assertIn("nothing to remove", result)
        self.assertEqual(self.sink.ops, [])


class TestPersistRendering(_ToolCase):
    """What a call leaves in the node: the block, and only on success."""

    def test_a_successful_add_renders_its_block(self) -> None:
        args = {"id": "loc.vault", "body": "# The Vault\n"}
        rendered = render_kb_op_persist(KB_ADD_TOOL, args, "OK: created loc.vault.")
        self.assertIsNotNone(rendered)
        ops = parse_kb_ops(rendered or "")
        self.assertEqual((ops[0].op, ops[0].id), ("add", "loc.vault"))
        self.assertEqual(ops[0].body, "# The Vault\n")

    def test_a_failed_call_renders_nothing(self) -> None:
        rendered = render_kb_op_persist(
            KB_ADD_TOOL, {"id": "loc.vault", "body": "x"}, "(error: nope)"
        )
        self.assertEqual(rendered, "")

    def test_a_no_op_patch_renders_nothing(self) -> None:
        args = {"id": "loc.vault", "patches": [{"start": {"target": "a"}, "content": "b"}]}
        self.assertEqual(
            render_kb_op_persist(KB_PATCH_PROPOSAL_TOOL, args, "OK: no changes for loc.vault"),
            "",
        )

    def test_another_tool_falls_through_to_the_default_fence(self) -> None:
        self.assertIsNone(render_kb_op_persist("kb_get", {"ids": ["x.y"]}, "OK"))

    def test_removing_a_proposed_object_still_persists_its_op(self) -> None:
        # Otherwise the earlier add block survives and materializes anyway.
        rendered = render_kb_op_persist(
            KB_REMOVE_TOOL, {"id": "loc.mistake"}, "OK: dropped your proposed loc.mistake."
        )
        ops = parse_kb_ops(rendered or "")
        self.assertEqual((ops[0].op, ops[0].id), ("remove", "loc.mistake"))

    def test_the_rendered_op_matches_what_the_sink_recorded(self) -> None:
        args = {"id": "loc.vault", "body": "# The Vault\n"}
        result = self.call(KB_ADD_TOOL, **args)
        rendered = render_kb_op_persist(KB_ADD_TOOL, args, result)
        self.assertEqual(parse_kb_ops(rendered or "")[0].body, self.sink.ops[0].body)


class TestBundleShape(_ToolCase):
    def test_all_four_verbs_are_offered(self) -> None:
        names = {tool["function"]["name"] for tool in self.tools}
        self.assertEqual(names, set(KB_OP_TOOLS))
        self.assertEqual(set(self.handlers), set(KB_OP_TOOLS))

    def test_patch_reuses_the_established_schema(self) -> None:
        from lens.core.command_tools import KB_PATCH_TOOL

        spec = next(t for t in self.tools if t["function"]["name"] == KB_PATCH_PROPOSAL_TOOL)
        self.assertEqual(spec["function"]["parameters"], KB_PATCH_TOOL.parameters)


if __name__ == "__main__":
    unittest.main()
