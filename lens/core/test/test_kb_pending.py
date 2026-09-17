"""Unit tests for the ``[kb-op …]: #`` channel and the pending fold."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lens.core.annotations import (
    parse_annotations,
    parse_front_matter,
    parse_tail_cursor_annotation,
    strip_markdown_comments,
)
from lens.core.kb_pending import (
    KB_OP_TAG,
    assert_block_safe,
    KbOp,
    KbOpSink,
    PendingLayer,
    decode_body,
    encode_body,
    fold,
    inflight_ops,
    inflight_sink,
    parse_kb_ops,
    render_kb_op,
    render_kb_ops,
    split_kb_op_blocks,
)
from lens.core.narrative import find_unclosed_cursor_annotation

# Every shape that has ever broken a markdown-comment channel in this repo,
# plus the ones the codec exists for.
BODY_CORPUS: list[str] = [
    "",
    "one line",
    "a\n\nb",
    "\n\n\n",
    "[foo]: #",
    "[design:abc]: #",
    "ends with ]: #",
    "trailing backslash \\",
    "double \\\\",
    "backslash then terminator ]: #\\",
    "tabs\there",
    "trailing spaces   ",
    "  leading spaces",
    "```kb\n---\nid: x.y\n---\nbody\n```",
    "<!-- ai:secret: hush -->",
    "x" * 400,
    "> [GM] brackets [a](b) [[c]] ]: # mid-line",
    "unicode — em dash ✓",
    "# Heading\n\n- bullet\n- bullet\n\n| table | head |\n|---|---|",
]


@dataclass
class FakeBase:
    """A :class:`~lens.core.kb_pending.PendingBase` backed by plain dicts."""

    texts: dict[str, str] = field(default_factory=dict[str, str])
    tags: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    dataset_only: set[str] = field(default_factory=set[str])

    def object_text(self, canonical_id: str) -> str | None:
        return self.texts.get(canonical_id)

    def object_tags(self, canonical_id: str) -> list[str]:
        return list(self.tags.get(canonical_id, []))

    def exists_on_disk(self, canonical_id: str) -> bool:
        return canonical_id in self.texts


def _node_with(block: str) -> str:
    """A realistic node: front matter, an operator block, the op inside it."""
    return (
        "[\n  kb_pin:\n    - person.amy\n]: #\n\n"
        "[write\n  prompt: continue\n]: #\n\n"
        "Visible prose.\n\n"
        f"{block}\n"
        "[/write]: #\n"
    )


class TestBodyCodec(unittest.TestCase):
    def test_round_trip_corpus(self) -> None:
        for body in BODY_CORPUS:
            with self.subTest(body=body):
                self.assertEqual(decode_body(encode_body(body)), body)

    def test_no_encoded_line_is_blank(self) -> None:
        for body in BODY_CORPUS:
            with self.subTest(body=body):
                for line in encode_body(body):
                    self.assertTrue(line.strip(), f"blank encoded line for {body!r}")

    def test_no_encoded_line_terminates_the_block(self) -> None:
        for body in BODY_CORPUS:
            with self.subTest(body=body):
                for line in encode_body(body):
                    self.assertFalse(
                        line.rstrip().endswith("]: #"),
                        f"encoded line would close the block: {line!r}",
                    )

    def test_hand_written_line_without_a_gutter_is_taken_literally(self) -> None:
        # Someone fixing a proposal by hand should not have to know the codec.
        self.assertEqual(decode_body(["| kept", "raw line"]), "kept\nraw line")


class TestRenderParseRoundTrip(unittest.TestCase):
    def test_add_round_trips_every_body(self) -> None:
        for body in BODY_CORPUS:
            with self.subTest(body=body):
                op = KbOp(op="add", id="loc.vault", body=body)
                parsed = parse_kb_ops(render_kb_op(op))
                self.assertEqual(len(parsed), 1)
                self.assertEqual(parsed[0].op, "add")
                self.assertEqual(parsed[0].id, "loc.vault")
                self.assertEqual(parsed[0].body, body)

    def test_patch_round_trips_nasty_content(self) -> None:
        patches: tuple[dict[str, Any], ...] = (
            {
                "start": {"target": "Line ]: #", "before": ["@@@start"]},
                "content": "a\n\nb\\\n]: #",
            },
            {"start": {"target": "✓ unicode"}, "content": ""},
        )
        op = KbOp(op="patch", id="loc.vault", patches=patches)
        parsed = parse_kb_ops(render_kb_op(op))
        self.assertEqual(parsed[0].patches, patches)

    def test_tag_round_trips_both_directions(self) -> None:
        op = KbOp(
            op="tag",
            id="timeline.epic",
            tags=("front.goblins", "cr:1-4"),
            remove_tags=("draft",),
        )
        parsed = parse_kb_ops(render_kb_op(op))[0]
        self.assertEqual(parsed.tags, ("front.goblins", "cr:1-4"))
        self.assertEqual(parsed.remove_tags, ("draft",))

    def test_remove_round_trips(self) -> None:
        parsed = parse_kb_ops(render_kb_op(KbOp(op="remove", id="loc.draft")))[0]
        self.assertEqual((parsed.op, parsed.id), ("remove", "loc.draft"))

    def test_applied_marker_round_trips(self) -> None:
        op = KbOp(
            op="applied",
            at="2026-09-16T12:04:11Z",
            session="design-tidewater",
            ids=("loc.vault", "npc.vasa"),
            removed=("loc.draft",),
        )
        parsed = parse_kb_ops(render_kb_op(op))[0]
        self.assertEqual(parsed.ids, ("loc.vault", "npc.vasa"))
        self.assertEqual(parsed.removed, ("loc.draft",))
        self.assertEqual(parsed.session, "design-tidewater")

    def test_ops_keep_document_order(self) -> None:
        text = render_kb_ops(
            [
                KbOp(op="add", id="loc.a", body="A"),
                KbOp(op="add", id="loc.b", body="B"),
                KbOp(op="remove", id="loc.a"),
            ]
        )
        self.assertEqual([op.id for op in parse_kb_ops(text)], ["loc.a", "loc.b", "loc.a"])

    def test_line_span_points_at_the_block(self) -> None:
        node = _node_with(render_kb_op(KbOp(op="add", id="loc.x", body="hi")))
        op = parse_kb_ops(node)[0]
        lines = node.split("\n")
        self.assertEqual(lines[op.line_start - 1].lstrip(), f"[{KB_OP_TAG}")
        self.assertTrue(lines[op.line_end - 1].rstrip().endswith("]: #"))

    def test_id_is_canonicalised(self) -> None:
        parsed = parse_kb_ops(render_kb_op(KbOp(op="add", id="Loc.Vault", body="x")))[0]
        self.assertEqual(parsed.id, "loc.vault")

    def test_unparseable_block_is_skipped_not_raised(self) -> None:
        text = "[kb-op\n  op: nonsense\n  id: loc.x\n]: #\n"
        self.assertEqual(parse_kb_ops(text), [])

    def test_scalars_that_yaml_would_type_coerce_stay_strings(self) -> None:
        # An unquoted timestamp reads back as a datetime and an unquoted "12"
        # as an int; both then str() into something other than what was
        # written, which is a silent round-trip failure rather than an error.
        op = KbOp(
            op="applied",
            at="2026-09-16T12:00:00Z",
            session="2026-01-01",
            ids=("loc.vault", "12", "true"),
        )
        parsed = parse_kb_ops(render_kb_op(op))[0]
        self.assertEqual(parsed.at, "2026-09-16T12:00:00Z")
        self.assertEqual(parsed.session, "2026-01-01")
        self.assertEqual(parsed.ids, ("loc.vault", "12", "true"))

    def test_free_text_fields_are_flattened_rather_than_leaked(self) -> None:
        # A field can carry an embedded newline; rendering must not put a blank
        # line inside the block, and the value must still come back intact.
        for value in ("oops\n\nblank", "ends with ]: #", "a\\b"):
            with self.subTest(value=value):
                op = KbOp(op="applied", session=value, ids=("loc.x",))
                rendered = render_kb_op(op)
                for line in rendered.split("\n")[:-2]:
                    self.assertTrue(line.strip())
                    self.assertFalse(line.rstrip().endswith("]: #"))
                self.assertEqual(parse_kb_ops(rendered)[0].session, value)

    def test_block_safety_backstop_raises_on_an_early_terminator(self) -> None:
        # Unreachable through the codec; the assertion is what makes a future
        # change that breaks the codec fail loudly instead of leaking a body.
        with self.assertRaises(ValueError):
            assert_block_safe("[kb-op\n  op: add\n  body: |\n    | x]: #\n    | y\n]: #\n")

    def test_block_safety_backstop_raises_on_a_blank_line(self) -> None:
        with self.assertRaises(ValueError):
            assert_block_safe("[kb-op\n  op: add\n\n  id: loc.x\n]: #\n")


class TestInvisibilityToEveryParser(unittest.TestCase):
    """The block must be inert to everything that reads a node."""

    def test_stripped_out_of_the_passage(self) -> None:
        for body in BODY_CORPUS:
            with self.subTest(body=body):
                node = _node_with(render_kb_op(KbOp(op="add", id="loc.x", body=body)))
                stripped = strip_markdown_comments(node)
                self.assertIn("Visible prose.", stripped)
                self.assertNotIn("loc.x", stripped)
                self.assertNotIn(KB_OP_TAG, stripped)

    def test_not_seen_as_an_annotation(self) -> None:
        node = _node_with(render_kb_op(KbOp(op="add", id="loc.x", body="a\n\nb")))
        self.assertEqual([a.operator for a in parse_annotations(node)], ["write", "write"])

    def test_does_not_disturb_cursor_detection(self) -> None:
        node = _node_with(render_kb_op(KbOp(op="add", id="loc.x", body="a\n\nb")))
        self.assertIsNone(find_unclosed_cursor_annotation(node))
        self.assertIsNone(parse_tail_cursor_annotation(node))

    def test_front_matter_still_reads(self) -> None:
        node = _node_with(render_kb_op(KbOp(op="add", id="loc.x", body="a")))
        self.assertEqual(parse_front_matter(node), {"kb_pin": ["person.amy"]})

    def test_a_leading_block_would_be_read_as_front_matter(self) -> None:
        """Documents the one placement that must never happen.

        ``ANNOTATION_OPEN_RE`` rejects the hyphen, so a ``[kb-op`` block at the
        top of a node is an unnamed comment — which is exactly what front matter
        is.  Composition puts these below the open tag, and this test is here so
        that a change which breaks the guarantee fails loudly.
        """
        leading = render_kb_op(KbOp(op="add", id="loc.x", body="a")) + "\nprose\n"
        self.assertEqual(parse_front_matter(leading).get("op"), "add")

    def test_split_lifts_blocks_out_before_a_reshape(self) -> None:
        block = render_kb_op(KbOp(op="add", id="loc.x", body="a"))
        remaining, blocks = split_kb_op_blocks(f"prose\n\n{block}\nmore\n")
        self.assertEqual(len(blocks), 1)
        self.assertNotIn(KB_OP_TAG, remaining)
        self.assertIn("prose", remaining)
        self.assertIn("more", remaining)

    def test_unterminated_block_runs_to_end_of_text(self) -> None:
        # Better to swallow the tail than to leak half a KB body as prose.
        text = "prose\n\n[kb-op\n  op: add\n  id: loc.x\n  body: |\n    | oops\n"
        remaining, blocks = split_kb_op_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("oops", remaining)


class TestFoldComposition(unittest.TestCase):
    def test_add_creates(self) -> None:
        layer = fold([KbOp(op="add", id="loc.x", body="body")], FakeBase())
        self.assertEqual(layer.objects["loc.x"], "body")
        self.assertIn("loc.x", layer.created)
        self.assertEqual(layer.errors, [])

    def test_second_add_replaces_the_first(self) -> None:
        layer = fold(
            [
                KbOp(op="add", id="loc.x", body="first"),
                KbOp(op="add", id="loc.x", body="second"),
            ],
            FakeBase(),
        )
        self.assertEqual(layer.objects["loc.x"], "second")

    def test_patches_compose_in_call_order(self) -> None:
        base = FakeBase(texts={"loc.x": "alpha\nbeta\n"})
        layer = fold(
            [
                KbOp(
                    op="patch",
                    id="loc.x",
                    patches=({"start": {"target": "alpha"}, "content": "ALPHA"},),
                ),
                KbOp(
                    op="patch",
                    id="loc.x",
                    patches=({"start": {"target": "ALPHA"}, "content": "final"},),
                ),
            ],
            base,
        )
        self.assertEqual(layer.errors, [])
        self.assertIn("final", layer.objects["loc.x"])
        self.assertNotIn("alpha", layer.objects["loc.x"])

    def test_patch_re_resolves_against_a_pending_add(self) -> None:
        layer = fold(
            [
                KbOp(op="add", id="loc.x", body="alpha\nbeta\n"),
                KbOp(
                    op="patch",
                    id="loc.x",
                    patches=({"start": {"target": "beta"}, "content": "BETA"},),
                ),
            ],
            FakeBase(),
        )
        self.assertEqual(layer.errors, [])
        self.assertIn("BETA", layer.objects["loc.x"])

    def test_remove_then_add_recreates(self) -> None:
        base = FakeBase(texts={"loc.x": "old"})
        layer = fold(
            [KbOp(op="remove", id="loc.x"), KbOp(op="add", id="loc.x", body="new")],
            base,
        )
        self.assertEqual(layer.objects["loc.x"], "new")
        self.assertNotIn("loc.x", layer.removed)

    def test_add_then_remove_leaves_nothing_to_materialize(self) -> None:
        layer = fold(
            [KbOp(op="add", id="loc.x", body="new"), KbOp(op="remove", id="loc.x")],
            FakeBase(),
        )
        self.assertNotIn("loc.x", layer.objects)
        self.assertNotIn("loc.x", layer.removed)
        self.assertNotIn("loc.x", layer.created)
        self.assertTrue(layer.is_empty())

    def test_remove_of_a_stored_object_is_recorded_for_deletion(self) -> None:
        layer = fold([KbOp(op="remove", id="loc.x")], FakeBase(texts={"loc.x": "old"}))
        self.assertIn("loc.x", layer.removed)
        self.assertNotIn("loc.x", layer.objects)

    def test_tags_accumulate_with_removals_applied_last(self) -> None:
        base = FakeBase(texts={"loc.x": "body"}, tags={"loc.x": ["place"]})
        layer = fold(
            [
                KbOp(op="tag", id="loc.x", tags=("draft", "sunken")),
                KbOp(op="tag", id="loc.x", tags=("lit",), remove_tags=("draft",)),
            ],
            base,
        )
        self.assertEqual(layer.tags["loc.x"], ["place", "sunken", "lit"])

    def test_tag_op_within_one_block_removes_after_adding(self) -> None:
        base = FakeBase(texts={"loc.x": "body"}, tags={"loc.x": []})
        layer = fold(
            [KbOp(op="tag", id="loc.x", tags=("a",), remove_tags=("a",))], base
        )
        self.assertEqual(layer.tags["loc.x"], [])

    def test_applied_markers_are_collected_not_folded(self) -> None:
        layer = fold([KbOp(op="applied", ids=("loc.x",))], FakeBase())
        self.assertEqual(len(layer.applied), 1)
        self.assertTrue(layer.is_empty())


class TestFoldErrors(unittest.TestCase):
    """A stale stack must fail descriptively, on every read."""

    def test_patch_against_a_missing_object(self) -> None:
        layer = fold(
            [
                KbOp(
                    op="patch",
                    id="loc.x",
                    patches=({"start": {"target": "a"}, "content": "b"},),
                )
            ],
            FakeBase(),
        )
        self.assertEqual(len(layer.errors), 1)
        self.assertIn("nothing to patch", layer.errors[0].reason)
        self.assertNotIn("loc.x", layer.objects)

    def test_patch_whose_anchor_the_user_edited_away(self) -> None:
        # The staleness case: valid when proposed, broken by a direct edit.
        base = FakeBase(texts={"loc.x": "the user rewrote this line\n"})
        op = KbOp(
            op="patch",
            id="loc.x",
            patches=({"start": {"target": "original anchor"}, "content": "new"},),
            line_start=12,
        )
        layer = fold([op], base)
        self.assertEqual(len(layer.errors), 1)
        self.assertEqual(layer.errors[0].line_start, 12)
        self.assertIn("target line not found", layer.errors[0].reason)
        self.assertNotIn("loc.x", layer.objects)

    def test_a_broken_op_does_not_stop_later_ops(self) -> None:
        base = FakeBase(texts={"loc.y": "keep\n"})
        layer = fold(
            [
                KbOp(
                    op="patch",
                    id="loc.missing",
                    patches=({"start": {"target": "a"}, "content": "b"},),
                ),
                KbOp(op="add", id="loc.z", body="landed"),
            ],
            base,
        )
        self.assertEqual(len(layer.errors), 1)
        self.assertEqual(layer.objects["loc.z"], "landed")

    def test_tag_and_remove_on_a_missing_object_report(self) -> None:
        layer = fold(
            [KbOp(op="tag", id="loc.x", tags=("a",)), KbOp(op="remove", id="loc.y")],
            FakeBase(),
        )
        self.assertEqual(len(layer.errors), 2)
        self.assertIn("nothing to tag", layer.errors[0].reason)
        self.assertIn("nothing to remove", layer.errors[1].reason)

    def test_add_without_a_body_reports(self) -> None:
        layer = fold([KbOp(op="add", id="loc.x")], FakeBase())
        self.assertIn("requires a body", layer.errors[0].reason)

    def test_error_renders_with_enough_to_find_the_block(self) -> None:
        layer = fold([KbOp(op="remove", id="loc.x", line_start=7)], FakeBase())
        rendered = str(layer.errors[0])
        self.assertIn("loc.x", rendered)
        self.assertIn("node line 7", rendered)


class TestStaleBaseMatrix(unittest.TestCase):
    """The base can move under a pending stack; each row of the matrix."""

    def test_add_whose_body_the_user_already_saved_is_a_no_op_in_effect(self) -> None:
        base = FakeBase(texts={"loc.x": "identical"})
        layer = fold([KbOp(op="add", id="loc.x", body="identical")], base)
        self.assertEqual(layer.objects["loc.x"], "identical")
        self.assertNotIn("loc.x", layer.created)

    def test_add_still_replaces_a_diverged_base(self) -> None:
        base = FakeBase(texts={"loc.x": "the user's version"})
        layer = fold([KbOp(op="add", id="loc.x", body="the model's version")], base)
        self.assertEqual(layer.objects["loc.x"], "the model's version")

    def test_patch_applies_to_the_new_text_when_the_anchor_survives(self) -> None:
        base = FakeBase(texts={"loc.x": "preamble the user added\nanchor\n"})
        layer = fold(
            [
                KbOp(
                    op="patch",
                    id="loc.x",
                    patches=({"start": {"target": "anchor"}, "content": "patched"},),
                )
            ],
            base,
        )
        self.assertEqual(layer.errors, [])
        self.assertIn("preamble the user added", layer.objects["loc.x"])
        self.assertIn("patched", layer.objects["loc.x"])

    def test_tag_already_present_is_a_no_op(self) -> None:
        base = FakeBase(texts={"loc.x": "b"}, tags={"loc.x": ["place"]})
        layer = fold([KbOp(op="tag", id="loc.x", tags=("place",))], base)
        self.assertEqual(layer.tags["loc.x"], ["place"])

    def test_remove_of_an_object_the_user_already_deleted_reports(self) -> None:
        layer = fold([KbOp(op="remove", id="loc.x")], FakeBase())
        self.assertEqual(len(layer.errors), 1)
        self.assertNotIn("loc.x", layer.removed)


class TestInflightSink(unittest.TestCase):
    def test_sink_is_scoped_to_the_context(self) -> None:
        root = Path("/tmp/lens-inflight-test")
        sink = KbOpSink()
        self.assertIsNone(inflight_sink(root))
        with inflight_ops(root, sink):
            self.assertIs(inflight_sink(root), sink)
        self.assertIsNone(inflight_sink(root))

    def test_nested_contexts_restore_the_outer_sink(self) -> None:
        root = Path("/tmp/lens-inflight-test")
        outer, inner = KbOpSink(), KbOpSink()
        with inflight_ops(root, outer):
            with inflight_ops(root, inner):
                self.assertIs(inflight_sink(root), inner)
            self.assertIs(inflight_sink(root), outer)
        self.assertIsNone(inflight_sink(root))

    def test_recording_bumps_the_revision(self) -> None:
        sink = KbOpSink()
        before = sink.revision
        sink.record(KbOp(op="add", id="loc.x", body="b"))
        self.assertNotEqual(sink.revision, before)
        self.assertEqual(len(sink.ops), 1)

    def test_empty_layer_is_empty(self) -> None:
        self.assertTrue(PendingLayer().is_empty())


if __name__ == "__main__":
    unittest.main()
