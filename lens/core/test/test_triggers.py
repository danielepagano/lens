"""Triggers (#195): front matter, done-by-node-name, offers, the two verbs, render.

A trigger's slug names the node it creates (``<slug>-tr``) and that node existing
is the only "done" state, so most of these tests are about names: what may be
called what, what counts as fired, and what a session close is allowed to offer.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.annotations import parse_front_matter, set_front_matter_key, strip_markdown_comments
from lens.core.command_tools import format_objects_for_model
from lens.core.context import (
    BLOCK_HELD_BACK,
    CrawlSpec,
    assemble_prompt,
    crawl,
    prompt_block_for_component,
)
from lens.core.exceptions import ValidationError
from lens.core.kb_op_tools import (
    KB_OP_TOOLS,
    KB_SET_TRIGGER_TOOL,
    KB_SUGGEST_TRIGGER_TOOL,
    build_kb_op_bundle,
    kb_op_persist_renderer,
)
from lens.core.kb_pending import KbOp, KbOpSink, fold, inflight_ops, parse_kb_ops, render_kb_op
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operators.design import DesignOperator
from lens.core.operators.session import slug_for_summary_prompt
from lens.core.project import ProjectSession
from lens.core.triggers import (
    TriggerError,
    declared_triggers,
    fired_slugs,
    normalize_trigger_run,
    normalize_trigger_slug,
    open_offers,
    parse_trigger_run,
    pins_at_or_above,
    session_trigger,
    suggested_slugs,
    triggers_from_text,
    with_trigger,
)

CELLAR_RUN = 'design --module encounter --pin prep.store "design the cellar"'

PREP_WITH_TRIGGER = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Enso opens the store cellar hatch\n"
    f"        run: '{CELLAR_RUN}'\n"
    "]: #\n"
    "\n"
    "The village store. Its cellar is held back.\n"
)


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


def _make_project(tmp: Path) -> None:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
    kb = tmp / "knowledge"
    (kb / "prep").mkdir(parents=True)
    (kb / "tags.toml").write_text("")
    (kb / "prep" / "store.md").write_text(PREP_WITH_TRIGGER)
    (kb / "prep" / "inn.md").write_text("The inn.\n")
    node_dir = tmp / "narrative" / "story"
    node_dir.mkdir(parents=True)
    (node_dir / "_node.md").write_text(
        "[\n    kb_pin:\n    - prep.store\n]: #\n\nEnso walks into the store.\n"
    )
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "init")


class _ProjectCase(unittest.TestCase):
    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.story = self.root / "narrative" / "story"

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def session(self) -> ProjectSession:
        KnowledgeStore.clear_registry()
        return ProjectSession(self.root, self.root)

    def narrative(self) -> NarrativeNode:
        n = self.session().active_narrative
        assert n is not None
        return n

    def open_session_node(self, name: str, params: str = "") -> Path:
        """Make *name* an open ``[design:<name>]`` session child of the root."""
        root_md = self.story / "_node.md"
        header = f"[design:{name}]: #" if not params else f"[design:{name}\n{params}]: #"
        root_md.write_text(root_md.read_text() + "\n" + header + "\n")
        child = self.story / f"{name}.md"
        child.write_text("")
        return child


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestFrontMatter(unittest.TestCase):
    def test_triggers_round_trip_and_leave_the_body_alone(self) -> None:
        text = "Body line.\n"
        out = with_trigger(text, "design-cellar", "Enso opens the hatch", CELLAR_RUN)
        self.assertTrue(out.endswith("Body line.\n"))
        found = triggers_from_text(out, "prep.store")
        self.assertEqual(set(found), {"design-cellar"})
        self.assertEqual(found["design-cellar"].run, CELLAR_RUN)
        self.assertEqual(found["design-cellar"].when, "Enso opens the hatch")
        # The front matter is a markdown comment: the crawl never shows it.
        self.assertNotIn("design-cellar", strip_markdown_comments(out))

    def test_upsert_keeps_other_keys_and_other_triggers(self) -> None:
        text = set_front_matter_key("Body\n", "tags", ["state"])
        text = with_trigger(text, "design-a", "a", "design")
        text = with_trigger(text, "design-b", "b", "design")
        text = with_trigger(text, "design-a", "a2", "design --pin prep.store")
        fm = parse_front_matter(text)
        self.assertEqual(fm["tags"], ["state"])
        found = triggers_from_text(text, "x.y")
        self.assertEqual(found["design-a"].when, "a2")
        self.assertIn("design-b", found)

    def test_empty_run_removes_and_drops_an_empty_block(self) -> None:
        text = with_trigger("Body\n", "design-a", "a", "design")
        text = with_trigger(text, "design-a", "", "")
        self.assertEqual(text, "Body\n")

    def test_malformed_entries_are_skipped_not_raised(self) -> None:
        text = "[\n    triggers:\n      design-a: just a string\n      design-b:\n        when: x\n]: #\nBody\n"
        self.assertEqual(triggers_from_text(text, "x.y"), {})


class TestSlugs(unittest.TestCase):
    def test_prefix_is_added_and_mismatch_refused(self) -> None:
        self.assertEqual(normalize_trigger_slug("cellar", "design"), "design-cellar")
        self.assertEqual(normalize_trigger_slug("design-cellar", "design"), "design-cellar")
        with self.assertRaises(TriggerError):
            normalize_trigger_slug("play-cellar", "design")

    def test_reserved_suffix_and_bad_characters_refused(self) -> None:
        with self.assertRaises(TriggerError):
            normalize_trigger_slug("cellar-tr", "design")
        with self.assertRaises(TriggerError):
            normalize_trigger_slug("the cellar", "design")

    def test_summary_titles_strip_the_reserved_suffix(self) -> None:
        self.assertEqual(slug_for_summary_prompt("design-cellar-tr"), "cellar")
        self.assertEqual(slug_for_summary_prompt("play-cellar-tr"), "cellar")

    def test_trigger_error_is_a_validation_error(self) -> None:
        # Every surface maps ValidationError to a user error, never a 500.
        with self.assertRaises(ValidationError):
            parse_trigger_run("advance")


class TestRun(unittest.TestCase):
    def test_parses_the_operator_subset(self) -> None:
        inv = parse_trigger_run(
            'design --module encounter -m clock --pin prep.store --include rules.x "build it"'
        )
        self.assertEqual(inv.operator, "design")
        self.assertEqual(inv.module_ids, ["encounter", "clock"])
        self.assertEqual(inv.pins, ["prep.store"])
        self.assertEqual(inv.includes, ["rules.x"])
        self.assertEqual(inv.prompt, "build it")
        self.assertFalse(inv.do_pass)

    def test_refuses_session_shaping_and_unknown_flags(self) -> None:
        for bad in ("design --slug x", "design --end", "play --retry", "design --weird 1"):
            with self.assertRaises(TriggerError, msg=bad):
                parse_trigger_run(bad)

    def test_refuses_non_session_operators(self) -> None:
        for bad in ("advance --days 2", "write hello", ""):
            with self.assertRaises(TriggerError, msg=bad):
                parse_trigger_run(bad)

    def test_promptless_play_passes_and_is_stored_explicitly(self) -> None:
        self.assertTrue(parse_trigger_run("play --pin encounter.cellar").do_pass)
        self.assertEqual(
            normalize_trigger_run("play --pin encounter.cellar"),
            "play --pin encounter.cellar --pass",
        )
        self.assertEqual(normalize_trigger_run("play --pass"), "play --pass")
        self.assertFalse(parse_trigger_run('play "I open it"').do_pass)


class TestSuggestMarkers(unittest.TestCase):
    def test_distinct_in_order(self) -> None:
        text = "a\n<!-- suggest:design-b -->\n<!--suggest: design-a-->\n<!-- suggest:design-b -->\n"
        self.assertEqual(suggested_slugs(text), ["design-b", "design-a"])


# ---------------------------------------------------------------------------
# Done: node names
# ---------------------------------------------------------------------------


class TestFiredSlugs(unittest.TestCase):
    def test_leaf_folder_and_nested_count_node_md_does_not(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "story"
            (root / "ch1" / "design-deep-tr").mkdir(parents=True)
            (root / "ch1" / "design-deep-tr" / "_node.md").write_text("")
            (root / "play-cellar-tr.md").write_text("")
            (root / "ch1" / "design-cellar-notes.md").write_text("")
            (root / "_node.md").write_text("")
            self.assertEqual(fired_slugs(root), {"design-deep", "play-cellar"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


class _Base:
    def __init__(self, objects: dict[str, str]) -> None:
        self.objects = objects

    def object_text(self, canonical_id: str) -> str | None:
        return self.objects.get(canonical_id)

    def object_tags(self, canonical_id: str) -> list[str]:
        del canonical_id
        return []

    def exists_on_disk(self, canonical_id: str) -> bool:
        return canonical_id in self.objects


class TestFold(unittest.TestCase):
    def test_render_parse_round_trip(self) -> None:
        op = KbOp(op="trigger", id="prep.store", slug="design-cellar",
                  when="Enso: opens the hatch]: #", run=CELLAR_RUN)
        (back,) = parse_kb_ops(render_kb_op(op))
        self.assertEqual((back.op, back.id, back.slug, back.when, back.run),
                         (op.op, op.id, op.slug, op.when, op.run))
        (sug,) = parse_kb_ops(render_kb_op(KbOp(op="suggest", slug="play-cellar")))
        self.assertEqual((sug.op, sug.slug, sug.id), ("suggest", "play-cellar", ""))

    def test_a_later_add_cannot_drop_an_earlier_trigger(self) -> None:
        ops = [
            KbOp(op="trigger", id="prep.new", slug="design-a", when="w", run="design"),
            KbOp(op="add", id="prep.new", body="Fresh body\n"),
        ]
        layer = fold(ops, _Base({}))
        self.assertEqual(layer.errors, [])
        self.assertIn("design-a", triggers_from_text(layer.objects["prep.new"], "prep.new"))
        self.assertIn("Fresh body", layer.objects["prep.new"])

    def test_trigger_on_a_missing_or_removed_object_is_an_error(self) -> None:
        ops = [
            KbOp(op="remove", id="prep.inn"),
            KbOp(op="trigger", id="prep.inn", slug="design-a", when="w", run="design"),
        ]
        layer = fold(ops, _Base({"prep.inn": "Inn\n"}))
        self.assertEqual(len(layer.errors), 1)
        self.assertEqual(layer.errors[0].index, 2)

    def test_suggest_touches_no_object(self) -> None:
        layer = fold([KbOp(op="suggest", slug="play-cellar")], _Base({"prep.store": "x"}))
        self.assertEqual(layer.objects, {})
        self.assertEqual([s.slug for s in layer.suggestions], ["play-cellar"])
        self.assertFalse(layer.is_empty())


# ---------------------------------------------------------------------------
# Store-level lookups and the two verbs
# ---------------------------------------------------------------------------


class TestDeclaredAndOffers(_ProjectCase):
    def test_declared_triggers_reads_front_matter(self) -> None:
        declared = declared_triggers(self.session().kb)
        self.assertEqual(declared["design-cellar"].declared_on, "prep.store")

    def test_an_offer_needs_a_marker_a_declaration_and_an_open_trigger(self) -> None:
        root_md = self.story / "_node.md"
        root_md.write_text(
            root_md.read_text()
            + "\n<!-- suggest:design-cellar -->\n<!-- suggest:design-unknown -->\n"
        )
        session = self.session()
        offers = open_offers(session.kb, self.narrative())
        self.assertEqual([o.slug for o in offers], ["design-cellar"])
        (self.story / "design-cellar-tr.md").write_text("")
        self.assertEqual(open_offers(session.kb, self.narrative()), [])

    def test_pins_at_or_above_walks_front_matter_only(self) -> None:
        self.open_session_node("design-x")
        node = NarrativeNode(narrative_root=self.story, key_path=("design-x",))
        self.assertEqual(pins_at_or_above(node), {"prep.store"})


class TestVerbs(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.sink = KbOpSink()
        bundle = build_kb_op_bundle(self.sink, self.root)
        self.handlers = bundle.handlers or {}
        self.tool_names = {t["function"]["name"] for t in bundle.tools or []}
        self._scope = inflight_ops(self.root, self.sink)
        self._scope.__enter__()

    def tearDown(self) -> None:
        self._scope.__exit__(None, None, None)
        super().tearDown()

    def call(self, name: str, **args: Any) -> str:
        async def _run() -> str:
            return await self.handlers[name](args, self.root)

        return asyncio.run(_run())

    def test_both_verbs_are_offered_and_unlogged(self) -> None:
        for name in (KB_SET_TRIGGER_TOOL, KB_SUGGEST_TRIGGER_TOOL):
            self.assertIn(name, self.tool_names)
            self.assertIn(name, KB_OP_TOOLS)

    def test_declare_records_a_normalized_op(self) -> None:
        out = self.call(KB_SET_TRIGGER_TOOL, id="prep.inn", slug="loft",
                        when="Enso climbs to the loft", run="play --pin prep.inn")
        self.assertTrue(out.startswith("OK:"), out)
        (op,) = self.sink.ops
        self.assertEqual((op.op, op.id, op.slug), ("trigger", "prep.inn", "play-loft"))
        self.assertEqual(op.run, "play --pin prep.inn --pass")
        # Visible to the next lookup in the same turn.
        self.assertIn("play-loft", declared_triggers(KnowledgeStore.for_project(self.root)))

    def test_slug_on_another_object_is_refused(self) -> None:
        out = self.call(KB_SET_TRIGGER_TOOL, id="prep.inn", slug="design-cellar",
                        when="w", run="design")
        self.assertIn("already declared on prep.store", out)
        self.assertEqual(self.sink.ops, [])

    def test_a_new_slug_that_would_be_born_done_is_refused(self) -> None:
        (self.story / "design-attic-tr.md").write_text("")
        out = self.call(KB_SET_TRIGGER_TOOL, id="prep.inn", slug="design-attic",
                        when="w", run="design")
        self.assertIn("born done", out)

    def test_bad_run_is_refused_in_turn(self) -> None:
        out = self.call(KB_SET_TRIGGER_TOOL, id="prep.inn", slug="design-x",
                        when="w", run="design --end")
        self.assertTrue(out.startswith("(error:"), out)

    def test_id_defaults_to_the_opener_and_the_block_says_so(self) -> None:
        self.open_session_node(
            "design-cellar-tr",
            "    trigger: design-cellar\n    trigger_from: prep.store\n    when: hatch\n",
        )
        args = {"slug": "play-cellar", "when": "Enso opens the hatch", "run": "play --pass"}
        out = self.call(KB_SET_TRIGGER_TOOL, **args)
        self.assertTrue(out.startswith("OK:"), out)
        self.assertEqual(self.sink.ops[0].id, "prep.store")
        block = kb_op_persist_renderer(self.root)(KB_SET_TRIGGER_TOOL, args, out)
        assert block
        (persisted,) = parse_kb_ops(block)
        self.assertEqual(persisted.id, "prep.store")

    def test_no_opener_and_no_id_is_an_error(self) -> None:
        out = self.call(KB_SET_TRIGGER_TOOL, slug="design-x", when="w", run="design")
        self.assertIn("'id' is required", out)

    def test_suggest_checks_exists_open_and_pinned_above(self) -> None:
        self.open_session_node("design-prep")
        self.assertIn("no such trigger", self.call(KB_SUGGEST_TRIGGER_TOOL, slug="design-nope"))
        # prep.inn is not pinned at or above the session's parent.
        self.call(KB_SET_TRIGGER_TOOL, id="prep.inn", slug="design-loft", when="w", run="design")
        self.assertIn("not in scope", self.call(KB_SUGGEST_TRIGGER_TOOL, slug="design-loft"))
        ok = self.call(KB_SUGGEST_TRIGGER_TOOL, slug="design-cellar")
        self.assertTrue(ok.startswith("OK:"), ok)
        (self.story / "design-cellar-tr.md").write_text("")
        self.assertIn("already done", self.call(KB_SUGGEST_TRIGGER_TOOL, slug="design-cellar"))


class TestTriggerProblems(_ProjectCase):
    def test_hand_written_mistakes_are_reported_not_skipped(self) -> None:
        from lens.core.triggers import trigger_problems

        (self.root / "knowledge" / "prep" / "inn.md").write_text(
            "[\n    triggers:\n"
            "      cellar:\n        when: w\n        run: design\n"
            "      design-loft:\n        when: w\n        run: design --end\n"
            "      design-cellar:\n        when: dup\n        run: design\n"
            "      design-attic:\n        run: design\n"
            "]: #\nInn\n"
        )
        problems = trigger_problems(self.session().kb)
        text = "\n".join(problems)
        self.assertIn("write it as 'design-cellar'", text)
        self.assertIn("design-loft': bad run", text)
        self.assertIn("also declared on", text)
        self.assertIn("design-attic': 'when' is missing", text)

    def test_clean_store_has_no_problems(self) -> None:
        from lens.core.triggers import trigger_problems

        self.assertEqual(trigger_problems(self.session().kb), [])


class TestHubScope(_ProjectCase):
    """A trigger on an object a `+` pin pulls in: play shows it, so suggest must accept it."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / "knowledge" / "npc").mkdir()
        (self.root / "knowledge" / "npc" / "phent.md").write_text(
            "[\n    triggers:\n      design-cellar-phent:\n"
            "        when: Phent opens the cellar\n        run: design\n]: #\nPhent.\n"
        )
        # `X+` pulls in the objects X is tagged with: the hub tags its members.
        KnowledgeStore.for_project(self.root).add_tags("prep.store", ["npc.phent"])
        root_md = self.story / "_node.md"
        root_md.write_text(root_md.read_text().replace("    - prep.store\n", "    - prep.store+\n"))

    def test_play_shows_it_and_suggest_accepts_it(self) -> None:
        from lens.core.triggers import check_suggestion, ids_in_scope_at

        self.open_session_node("design-x")
        parent = NarrativeNode(narrative_root=self.story, key_path=())
        self.assertIn("npc.phent", ids_in_scope_at(parent))
        reason = check_suggestion(
            "design-cellar-phent",
            declared=declared_triggers(self.session().kb),
            fired=set(),
            parent=parent,
        )
        self.assertIsNone(reason)
        result = crawl(CrawlSpec.of(parent))
        user = assemble_prompt(result, system_prompt="S", instruction="T", held_back=True)[-1]["content"]
        self.assertIn("- design-cellar-phent: Phent opens the cellar", user)


class TestMisplacedFrontMatter(_ProjectCase):
    def test_a_triggers_block_below_the_body_is_reported(self) -> None:
        from lens.core.triggers import trigger_problems

        (self.root / "knowledge" / "prep" / "inn.md").write_text(
            "The inn.\n\n[\n    triggers:\n      design-attic:\n"
            "        when: w\n        run: design\n]: #\n"
        )
        self.assertEqual(declared_triggers(self.session().kb).get("design-attic"), None)
        text = "\n".join(trigger_problems(self.session().kb))
        self.assertIn("prep.inn: a 'triggers:' block is not the first thing in the file", text)

    def test_body_prose_about_triggers_is_not_flagged(self) -> None:
        from lens.core.triggers import trigger_problems

        (self.root / "knowledge" / "prep" / "inn.md").write_text(
            "The inn.\n\ntriggers:\n  - the bell rings\n"
        )
        self.assertEqual(trigger_problems(self.session().kb), [])


class TestKbGetShowsTriggers(_ProjectCase):
    def test_browsing_output_carries_the_map(self) -> None:
        kb = self.session().kb
        out = format_objects_for_model(kb.get_objects(["prep.store", "prep.inn"]))
        self.assertIn("TRIGGERS", out)
        self.assertIn("design-cellar", out)
        self.assertIn(CELLAR_RUN, out)


# ---------------------------------------------------------------------------
# Sessions opened by a trigger
# ---------------------------------------------------------------------------


class TestFireSession(_ProjectCase):
    def setup(self, **kw: Any) -> tuple[NarrativeNode, Any]:
        session = self.session()
        narrative = self.narrative()

        async def _go() -> tuple[NarrativeNode, Any]:
            return await DesignOperator._setup_fresh_session(  # pyright: ignore[reportPrivateUsage]
                session=session,
                narrative=narrative,
                prompt=None,
                module_ids=None,
                pins=[],
                unpins=[],
                on_stream_target=None,
                **kw,
            )

        return asyncio.run(_go())

    def test_names_the_node_and_records_the_origin(self) -> None:
        node, _ = self.setup(trigger="design-cellar")
        self.assertEqual(node.key_path, ("design-cellar-tr",))
        origin = session_trigger(node, "design")
        assert origin is not None
        self.assertEqual(origin.slug, "design-cellar")
        self.assertEqual(origin.declared_on, "prep.store")
        self.assertEqual(origin.when, "Enso opens the store cellar hatch")
        self.assertIn("design-cellar", fired_slugs(self.story))

    def test_refuses_done_unknown_and_foreign_triggers(self) -> None:
        (self.story / "design-cellar-tr.md").write_text("")
        with self.assertRaises(ValidationError):
            self.setup(trigger="design-cellar")
        with self.assertRaises(ValidationError):
            self.setup(trigger="design-nope")
        with self.assertRaises(ValidationError):
            self.setup(trigger="play-cellar")

    def test_slug_may_not_claim_the_reserved_suffix(self) -> None:
        with self.assertRaises(ValidationError):
            self.setup(slug="cellar-tr")

    def test_auto_names_never_end_in_the_suffix(self) -> None:
        root = NarrativeNode(narrative_root=self.story, key_path=())
        name = DesignOperator.generate_session_id("go to tr", None, root)
        self.assertFalse(name.endswith("-tr"), name)

    def test_task_says_why_the_session_opened(self) -> None:
        node, _ = self.setup(trigger="design-cellar")
        session = self.session()
        op = DesignOperator(session.new_storage(), self.narrative())
        result = crawl(CrawlSpec.of(node))
        out = op.append_trigger_context(result, "Do the thing.")
        # Design's own line: build for the moment, then owe the follow-up.
        self.assertIn("opened by the trigger design-cellar: Enso opens the store cellar hatch", out)
        self.assertIn("suggest_trigger", out)
        self.assertIn("defaults to prep.store", out)
        from lens.rpg.operators.play import PlayOperator

        self.assertEqual(PlayOperator.trigger_opened_prompt_key, "session.trigger_opened")


# ---------------------------------------------------------------------------
# The held-back block
# ---------------------------------------------------------------------------


class TestHeldBack(_ProjectCase):
    def render(self, *, held_back: bool, turns: list[tuple[str, str]] | None = None) -> list[dict[str, str]]:
        root = NarrativeNode(narrative_root=self.story, key_path=())
        result = crawl(CrawlSpec.of(root))
        return assemble_prompt(
            result, system_prompt="SYS", instruction="TASK TEXT", turns=turns, held_back=held_back
        )

    def test_renders_open_triggers_before_the_task(self) -> None:
        user = self.render(held_back=True)[-1]["content"]
        self.assertIn("--- begin HELD BACK ---", user)
        self.assertIn("- design-cellar: Enso opens the store cellar hatch", user)
        self.assertLess(user.index("HELD BACK"), user.index("TASK TEXT"))
        self.assertGreater(user.index("HELD BACK"), user.index("RELEVANT KNOWLEDGE"))
        # The run never reaches the model.
        self.assertNotIn("--module encounter", user)

    def test_turns_path_puts_it_with_the_task(self) -> None:
        msgs = self.render(held_back=True, turns=[("user", "u1"), ("assistant", "a1"), ("user", "u2")])
        self.assertIn("HELD BACK", msgs[-1]["content"])
        self.assertNotIn("HELD BACK", msgs[1]["content"])

    def test_only_when_asked_and_only_while_open(self) -> None:
        self.assertNotIn("HELD BACK", self.render(held_back=False)[-1]["content"])
        (self.story / "design-cellar-tr.md").write_text("")
        user = self.render(held_back=True)[-1]["content"]
        self.assertNotIn("HELD BACK", user)
        self.assertNotIn("suggest:", user)

    def test_block_is_attributed_for_explain(self) -> None:
        root = NarrativeNode(narrative_root=self.story, key_path=())
        result = crawl(CrawlSpec.of(root))
        assemble_prompt(result, system_prompt="S", instruction="T", held_back=True)
        graph = result.render_graph
        assert graph is not None
        held = [c for c in graph.components if c.kind == "held_back"]
        self.assertEqual(len(held), 1)
        self.assertEqual(prompt_block_for_component(held[0]), BLOCK_HELD_BACK)


if __name__ == "__main__":
    unittest.main()
