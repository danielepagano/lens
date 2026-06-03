"""Unit tests for kb_patch core function and the kb_patch command tool def."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.command_tools import KB_PATCH_TOOL, kb_patch_handler  # noqa: F401
from lens.core.commands.kb import kb_patch
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.text_select import (
    END_ANCHOR,
    START_ANCHOR,
    LineSelector,
    Patch,
    Selection,
)


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
    (tmp / "lens.toml").write_text('[project]\nnarrative = "test"\n')
    (tmp / "narrative" / "test").mkdir(parents=True)
    (tmp / "narrative" / "test" / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )
    return tmp


def _write_kb(root: Path, canonical_id: str, text: str) -> Path:
    type_name, key = canonical_id.split(".", 1)
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "kb"], cwd=root, capture_output=True, check=True
    )
    return path


def _sel(
    target: str,
    before: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
) -> LineSelector:
    return LineSelector(target=target, before=before, after=after)


class _KbPatchTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = _init_repo(Path(self._tmpdir.name))
        KnowledgeStore.clear_registry()
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Direct kb_patch core function tests (using text_select Patch objects).
# ---------------------------------------------------------------------------


class TestKbPatchCore(_KbPatchTestBase):
    def test_replace_single_line(self) -> None:
        path = _write_kb(self.root, "person.amy", "Amy is a baker.\nLives in NYC.\n")
        patches = [
            Patch(
                selection=Selection(start=_sel("Amy is a baker.")),
                content="Amy is a novelist.",
            )
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "Amy is a novelist.\nLives in NYC.\n")

    def test_replace_range(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "line1\nline2\nline3\nline4\n",
        )
        patches = [
            Patch(
                selection=Selection(start=_sel("line2"), end=_sel("line3")),
                content="LINE",
            )
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "line1\nLINE\nline4\n")

    def test_append_with_end_anchor(self) -> None:
        path = _write_kb(self.root, "person.amy", "Amy is a baker.\n")
        patches = [
            Patch(
                selection=Selection(start=_sel(END_ANCHOR)),
                content="Lives in NYC.",
            )
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "Amy is a baker.\nLives in NYC.\n")

    def test_prepend_with_start_anchor(self) -> None:
        path = _write_kb(self.root, "person.amy", "Amy is a baker.\n")
        patches = [
            Patch(
                selection=Selection(start=_sel(START_ANCHOR)),
                content="Name: Amy",
            )
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "Name: Amy\nAmy is a baker.\n")

    def test_full_replace(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "old content\nhere\n",
        )
        patches = [
            Patch(
                selection=Selection(
                    start=_sel(START_ANCHOR),
                    end=_sel(END_ANCHOR),
                ),
                content="new content",
            )
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "new content\n")

    def test_multiple_patches_applied_in_order(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "one\ntwo\nthree\n",
        )
        patches = [
            Patch(selection=Selection(start=_sel("one")), content="ONE"),
            Patch(selection=Selection(start=_sel("three")), content="THREE"),
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "ONE\ntwo\nTHREE\n")

    def test_delete_with_empty_content(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "keep\ndelete\nkeep\n",
        )
        patches = [
            Patch(selection=Selection(start=_sel("delete")), content="")
        ]
        kb_patch("person.amy", patches, store=self.store)
        self.assertEqual(path.read_text(), "keep\nkeep\n")


# ---------------------------------------------------------------------------
# kb_patch from a dict payload (the tool-call shape).
# ---------------------------------------------------------------------------


class TestKbPatchFromDict(_KbPatchTestBase):
    def test_dict_patch(self) -> None:
        path = _write_kb(self.root, "person.amy", "alpha\nbeta\ngamma\n")
        kb_patch(
            "person.amy",
            [{"start": {"target": "beta"}, "content": "BETA"}],
            store=self.store,
        )
        self.assertEqual(path.read_text(), "alpha\nBETA\ngamma\n")

    def test_dict_range_with_context(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "a\nfoo\nb\nfoo\nc\n",
        )
        kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": "foo", "before": ["a"]},
                    "end": {"target": "foo", "before": ["b"]},
                    "content": "FOO",
                }
            ],
            store=self.store,
        )
        self.assertEqual(path.read_text(), "a\nFOO\nc\n")

    def test_dict_patch_with_anchors(self) -> None:
        path = _write_kb(self.root, "person.amy", "body\n")
        kb_patch(
            "person.amy",
            [
                {"start": {"target": START_ANCHOR}, "content": "HEAD"},
                {"start": {"target": END_ANCHOR}, "content": "TAIL"},
            ],
            store=self.store,
        )
        self.assertEqual(path.read_text(), "HEAD\nbody\nTAIL\n")


# ---------------------------------------------------------------------------
# Validation / error handling
# ---------------------------------------------------------------------------


class TestKbPatchValidation(_KbPatchTestBase):
    def test_rejects_invalid_id(self) -> None:
        with self.assertRaises(LensException):
            kb_patch("invalid-id", [{"start": {"target": "x"}, "content": "y"}], store=self.store)

    def test_rejects_template_id(self) -> None:
        with self.assertRaises(LensException) as ctx:
            kb_patch(
                "person._template",
                [{"start": {"target": "x"}, "content": "y"}],
                store=self.store,
            )
        self.assertIn("template", str(ctx.exception).lower())

    def test_object_not_found(self) -> None:
        with self.assertRaises(LensException) as ctx:
            kb_patch(
                "person.missing",
                [{"start": {"target": "x"}, "content": "y"}],
                store=self.store,
            )
        self.assertIn("not found", str(ctx.exception))

    def test_empty_patches_raises(self) -> None:
        _write_kb(self.root, "person.amy", "hi\n")
        with self.assertRaises(LensException) as ctx:
            kb_patch("person.amy", [], store=self.store)
        self.assertIn("at least one patch", str(ctx.exception))

    def test_none_patches_raises(self) -> None:
        _write_kb(self.root, "person.amy", "hi\n")
        with self.assertRaises(LensException):
            kb_patch("person.amy", None, store=self.store)

    def test_malformed_patch_dict_raises(self) -> None:
        _write_kb(self.root, "person.amy", "hi\n")
        with self.assertRaises(LensException) as ctx:
            kb_patch(
                "person.amy",
                [{"content": "x"}],  # missing start
                store=self.store,
            )
        self.assertIn("start", str(ctx.exception))

    def test_unresolvable_patch_does_not_mutate(self) -> None:
        path = _write_kb(self.root, "person.amy", "hi\n")
        original = path.read_text()
        with self.assertRaises(LensException) as ctx:
            kb_patch(
                "person.amy",
                [{"start": {"target": "not there"}, "content": "x"}],
                store=self.store,
            )
        self.assertIn("no match", str(ctx.exception))
        # File must be untouched on failure.
        self.assertEqual(path.read_text(), original)

    def test_ambiguous_patch_error_is_actionable(self) -> None:
        _write_kb(self.root, "person.amy", "x\nfoo\ny\nfoo\nz\n")
        with self.assertRaises(LensException) as ctx:
            kb_patch(
                "person.amy",
                [{"start": {"target": "foo"}, "content": "FOO"}],
                store=self.store,
            )
        msg = str(ctx.exception)
        self.assertIn("ambiguous", msg)

    def test_no_changes_skips_store(self) -> None:
        path = _write_kb(self.root, "person.amy", "Amy is a baker.\n")
        original = path.read_text()
        result = kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": "Amy is a baker."},
                    "content": "Amy is a baker.",
                }
            ],
            store=self.store,
        )
        self.assertEqual(result.kind, "no_changes")
        self.assertEqual(path.read_text(), original)

    def test_already_present_when_content_exists(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "Amy is a baker.\nTrust shifted after Tuesday.\n",
        )
        original = path.read_text()
        result = kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": "Planned coffee on Tuesday."},
                    "content": "Trust shifted after Tuesday.",
                }
            ],
            store=self.store,
        )
        self.assertEqual(result.kind, "already_present")
        self.assertEqual(path.read_text(), original)

    def test_already_present_when_append_block_already_in_file(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "section\n- Trust shifted.\n",
        )
        original = path.read_text()
        result = kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": END_ANCHOR},
                    "content": "section\n- Trust shifted.",
                }
            ],
            store=self.store,
        )
        self.assertEqual(result.kind, "already_present")
        self.assertEqual(path.read_text(), original)

    def test_stale_anchor_after_prior_success_is_idempotent(self) -> None:
        path = _write_kb(
            self.root,
            "person.amy",
            "Planned coffee on Tuesday.\n",
        )
        first = kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": "Planned coffee on Tuesday."},
                    "content": "Completed Tuesday date.",
                }
            ],
            store=self.store,
        )
        self.assertEqual(first.kind, "patched")
        second = kb_patch(
            "person.amy",
            [
                {
                    "start": {"target": "Planned coffee on Tuesday."},
                    "content": "Completed Tuesday date.",
                }
            ],
            store=self.store,
        )
        self.assertEqual(second.kind, "already_present")
        self.assertEqual(
            path.read_text(),
            "Completed Tuesday date.\n",
        )


# ---------------------------------------------------------------------------
# kb_patch_handler async handler (the command_tools glue that operators would call).
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


class TestKbPatchHandler(_KbPatchTestBase):
    def test_handler_success_returns_ok_and_formatted_object(self) -> None:
        path = _write_kb(self.root, "person.amy", "Amy is a baker.\n")
        args = {
            "id": "person.amy",
            "patches": [
                {
                    "start": {"target": "Amy is a baker."},
                    "content": "Amy is a novelist.",
                }
            ],
        }
        result = _run(kb_patch_handler(args, self.root))
        self.assertTrue(result.startswith("OK: patched person.amy"))
        self.assertIn("Amy is a novelist.", result)
        self.assertEqual(path.read_text(), "Amy is a novelist.\n")

    def test_handler_missing_id(self) -> None:
        result = _run(kb_patch_handler({"patches": [{"start": {"target": "x"}, "content": "y"}]}, self.root))
        self.assertIn("error", result)
        self.assertIn("id", result)

    def test_handler_non_string_id(self) -> None:
        result = _run(kb_patch_handler({"id": 123, "patches": [{"start": {"target": "x"}, "content": "y"}]}, self.root))
        self.assertIn("error", result)

    def test_handler_empty_patches(self) -> None:
        result = _run(kb_patch_handler({"id": "person.amy", "patches": []}, self.root))
        self.assertIn("error", result)
        self.assertIn("patches", result)

    def test_handler_non_list_patches(self) -> None:
        result = _run(kb_patch_handler({"id": "person.amy", "patches": "not a list"}, self.root))
        self.assertIn("error", result)

    def test_handler_object_not_found_returns_error_string(self) -> None:
        result = _run(
            kb_patch_handler(
                {
                    "id": "person.ghost",
                    "patches": [{"start": {"target": "x"}, "content": "y"}],
                },
                self.root,
            )
        )
        self.assertIn("error", result)
        self.assertIn("not found", result)

    def test_handler_unresolvable_selection_returns_error_string(self) -> None:
        _write_kb(self.root, "person.amy", "real content\n")
        result = _run(
            kb_patch_handler(
                {
                    "id": "person.amy",
                    "patches": [
                        {"start": {"target": "missing"}, "content": "X"}
                    ],
                },
                self.root,
            )
        )
        self.assertIn("error", result)
        self.assertIn("no match", result)


# ---------------------------------------------------------------------------
# The tool definition itself — verify the schema is sensible for an LLM.
# ---------------------------------------------------------------------------


class TestKbPatchToolDef(unittest.TestCase):
    def test_description_mentions_anchors(self) -> None:
        desc = KB_PATCH_TOOL.description
        self.assertIn("@@@start", desc)
        self.assertIn("@@@end", desc)

    def test_description_mentions_context_disambiguation(self) -> None:
        desc = KB_PATCH_TOOL.description.lower()
        self.assertIn("before", desc)
        self.assertIn("after", desc)

    def test_schema_top_level_required(self) -> None:
        params = KB_PATCH_TOOL.parameters
        self.assertEqual(params["type"], "object")
        self.assertIn("id", params["required"])
        self.assertIn("patches", params["required"])

    def test_schema_id_is_string(self) -> None:
        props = KB_PATCH_TOOL.parameters["properties"]
        self.assertEqual(props["id"]["type"], "string")

    def test_schema_patches_is_array(self) -> None:
        props = KB_PATCH_TOOL.parameters["properties"]
        patches_schema = props["patches"]
        self.assertEqual(patches_schema["type"], "array")
        self.assertIn("items", patches_schema)

    def test_schema_patch_item_has_start_and_content_required(self) -> None:
        item = KB_PATCH_TOOL.parameters["properties"]["patches"]["items"]
        self.assertEqual(item["type"], "object")
        self.assertIn("start", item["required"])
        self.assertIn("content", item["required"])
        # end is optional
        self.assertNotIn("end", item["required"])

    def test_schema_selector_has_target_required(self) -> None:
        item = KB_PATCH_TOOL.parameters["properties"]["patches"]["items"]
        start_schema = item["properties"]["start"]
        self.assertIn("target", start_schema["required"])
        before_schema = start_schema["properties"]["before"]
        after_schema = start_schema["properties"]["after"]
        self.assertEqual(before_schema["type"], "array")
        self.assertEqual(before_schema["items"]["type"], "string")
        self.assertEqual(after_schema["type"], "array")
        self.assertEqual(after_schema["items"]["type"], "string")

    def test_schema_end_selector_also_defined(self) -> None:
        item = KB_PATCH_TOOL.parameters["properties"]["patches"]["items"]
        self.assertIn("end", item["properties"])
        end_schema = item["properties"]["end"]
        self.assertIn("target", end_schema["required"])

    def test_tool_not_in_default_registry(self) -> None:
        """The task asks that kb_patch not be exposed to any operator yet."""
        from lens.core.command_tools import get_command_registry

        registry = get_command_registry(None)
        self.assertNotIn("kb_patch", registry)
