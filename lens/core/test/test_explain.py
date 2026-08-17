"""Tests for ``lens explain`` — context composition reporting."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.explain import (
    BLOCK_CONVERSATION,
    SORT_SIZE,
    ExplainBlock,
    ExplainReport,
    component_provenance,
    detect_operator_name,
    estimate_tokens,
    explain_context,
)
from lens.core.context import (
    BLOCK_CURRENT,
    BLOCK_KNOWLEDGE,
    BLOCK_STATE,
    BLOCK_SYSTEM,
    BLOCK_TASK,
)
from lens.core.crawl_graph import ComponentKind, CrawlComponent
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.pinning import pin
from lens.core.project import ProjectSession
from lens.testing.project import setup_test_project


def _block(report: ExplainReport, block_id: str) -> ExplainBlock | None:
    return next((b for b in report.blocks if b.id == block_id), None)


class ExplainTestCase(unittest.TestCase):
    """Shared throwaway project: person.amy pinned at the narrative root."""

    session: ProjectSession
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        cls.tmp = tempfile.mkdtemp(prefix="lens_explain_")
        cls.session = setup_test_project(
            Path(cls.tmp), "http://127.0.0.1:1/v1", opening_write=False
        )
        narrative = cls.session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        cursor.md_path().write_text(
            cursor.md_path().read_text(encoding="utf-8")
            + "\nAmy walked into the forest and did not look back.\n",
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()


class TestExplainBasics(ExplainTestCase):
    def test_reports_the_detected_operator_and_cursor(self) -> None:
        report = explain_context(self.session)
        self.assertEqual(report.operator, "write")
        self.assertTrue(report.node.startswith("story"))
        self.assertGreater(report.total_bytes, 0)

    def test_system_and_task_blocks_are_present(self) -> None:
        report = explain_context(self.session)
        ids = {b.id for b in report.blocks}
        self.assertIn(BLOCK_SYSTEM, ids)
        self.assertIn(BLOCK_TASK, ids)

    def test_pinned_kb_object_is_reported_with_node_pin_provenance(self) -> None:
        report = explain_context(self.session)
        knowledge = _block(report, BLOCK_KNOWLEDGE)
        assert knowledge is not None
        amy = next(c for c in knowledge.components if c.id == "kb:person.amy")
        self.assertEqual(amy.provenance_kind, "node_pin")
        self.assertIn("kb_pin on", amy.provenance)
        self.assertGreater(amy.bytes, 0)
        self.assertGreater(amy.tokens, 0)

    def test_current_passage_carries_the_narrative_text(self) -> None:
        report = explain_context(self.session)
        current = _block(report, BLOCK_CURRENT)
        assert current is not None
        self.assertEqual(len(current.components), 1)
        self.assertEqual(current.components[0].provenance_kind, "narrative")

    def test_totals_account_for_every_byte_of_every_message(self) -> None:
        report = explain_context(self.session)
        self.assertEqual(report.total_bytes, sum(report.message_bytes))
        self.assertEqual(
            report.accounted_bytes + report.other_bytes, report.total_bytes
        )
        # Only message joining should be unaccounted for, not whole blocks.
        self.assertLess(report.other_bytes, 32)

    def test_block_bytes_cover_their_components_plus_framing(self) -> None:
        report = explain_context(self.session)
        for block in report.blocks:
            self.assertEqual(
                block.bytes,
                sum(c.bytes for c in block.components) + block.framing_bytes,
                f"block {block.id} does not add up",
            )

    def test_percentages_are_relative_to_the_grand_total(self) -> None:
        report = explain_context(self.session)
        total_pct = sum(b.percent for b in report.blocks)
        self.assertGreater(total_pct, 50.0)
        self.assertLessEqual(total_pct, 100.5)

    def test_block_tokens_cover_their_components_plus_framing(self) -> None:
        report = explain_context(self.session)
        for block in report.blocks:
            self.assertEqual(
                block.tokens,
                sum(c.tokens for c in block.components) + block.framing_tokens,
                f"block {block.id} token column does not add up",
            )

    def test_framing_tokens_are_never_negative(self) -> None:
        report = explain_context(self.session)
        for block in report.blocks:
            self.assertGreaterEqual(block.framing_tokens, 0)

    def test_report_totals_are_the_sum_of_the_blocks(self) -> None:
        report = explain_context(self.session)
        self.assertEqual(
            report.total_tokens,
            sum(b.tokens for b in report.blocks) + report.other_tokens,
        )
        self.assertEqual(
            report.total_bytes,
            sum(b.bytes for b in report.blocks) + report.other_bytes,
        )

    def test_wrapped_blocks_charge_tokens_for_their_framing(self) -> None:
        report = explain_context(self.session)
        knowledge = _block(report, BLOCK_KNOWLEDGE)
        assert knowledge is not None
        # The `--- begin/end RELEVANT KNOWLEDGE ---` wrapper is real cost.
        self.assertGreater(knowledge.framing_bytes, 0)
        self.assertGreater(knowledge.framing_tokens, 0)

    def test_unwrapped_blocks_have_no_framing(self) -> None:
        report = explain_context(self.session)
        system = _block(report, BLOCK_SYSTEM)
        assert system is not None
        self.assertEqual(system.framing_bytes, 0)
        self.assertEqual(system.framing_tokens, 0)

    def test_cache_positions_are_labelled(self) -> None:
        report = explain_context(self.session)
        by_id = {b.id: b.cache for b in report.blocks}
        self.assertEqual(by_id[BLOCK_SYSTEM], "prefix")
        self.assertEqual(by_id[BLOCK_KNOWLEDGE], "prefix")
        self.assertEqual(by_id[BLOCK_TASK], "volatile")

    def test_payload_carries_no_presentation_text(self) -> None:
        # Explanatory prose belongs to each surface (and its locale), not to
        # the report; the payload carries only machine values.
        payload = explain_context(self.session).to_dict()
        self.assertNotIn("cache_note", payload)


class TestExplainCountsMentionsWhereTheyLand(unittest.TestCase):
    """Mentions expand inside the passage, so their bytes must be counted there.

    Both renderings are checked: the single-turn ``current_passage`` block and
    the multi-turn ``conversation`` block, because those take different code
    paths to the node text and a mention must not disappear from either.
    """

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self.tmp = tempfile.mkdtemp(prefix="lens_explain_mentions_")
        self.session = setup_test_project(
            Path(self.tmp), "http://127.0.0.1:1/v1", opening_write=False
        )
        kb_dir = Path(self.tmp) / "knowledge" / "rules"
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / "grappling.md").write_text(
            "Grappling costs one action and provokes nothing.\n", encoding="utf-8"
        )
        # Deliberately not pinned: a pinned id is suppressed in place, so a
        # second *unpinned* object is what exercises two adjacent expansions.
        (kb_dir / "cover.md").write_text(
            "Half cover grants +2 AC.\n", encoding="utf-8"
        )
        # A KB body that a later transform rewrites: `ai:secret` is stored
        # ROT13 and reaches the model decoded, so the block in the passage is
        # not byte-identical to the one the renderer emitted.
        lore_dir = Path(self.tmp) / "knowledge" / "lore"
        lore_dir.mkdir(parents=True, exist_ok=True)
        (lore_dir / "bridge.md").write_text(
            "The bridge is old.\n\n<!-- ai:secret:\nGur gerfnher\n-->\n",
            encoding="utf-8",
        )
        (lore_dir / "map.md").write_text(
            "A creased map.\n\n![x](/mount/file/map.png)\n", encoding="utf-8"
        )
        tracker_dir = Path(self.tmp) / "knowledge" / "tracker"
        tracker_dir.mkdir(parents=True, exist_ok=True)
        (tracker_dir / "combat.md").write_text("Goblin HP 7/7\n", encoding="utf-8")
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        KnowledgeStore.for_project(Path(self.tmp)).add_tags("tracker.combat", ["state"])
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        narrative = self.session.active_narrative
        assert narrative is not None
        self.cursor = narrative.find_cursor()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def _bytes_with_and_without(self, body: str, block_id: str) -> tuple[int, int]:
        path = self.cursor.md_path()
        base = path.read_text(encoding="utf-8")
        path.write_text(base + body, encoding="utf-8")
        without = _block(explain_context(self.session), block_id)
        path.write_text(
            base + body + "[include: rules.grappling]: #\n", encoding="utf-8"
        )
        with_include = _block(explain_context(self.session), block_id)
        assert without is not None and with_include is not None
        return without.bytes, with_include.bytes

    def test_single_turn_passage_grows_by_the_expanded_block(self) -> None:
        without, with_include = self._bytes_with_and_without(
            "\nAmy walked on.\n", BLOCK_CURRENT
        )
        self.assertGreater(with_include, without)

    def test_conversation_turns_grow_by_the_expanded_block(self) -> None:
        without, with_include = self._bytes_with_and_without(
            "\n[write]: #\n\nAmy walked on.\n\n[/write]: #\n", BLOCK_CONVERSATION
        )
        self.assertGreater(with_include, without)

    def _rows(self, block_id: str) -> list[str]:
        block = _block(explain_context(self.session), block_id)
        return [] if block is None else [c.id for c in block.components]

    def test_expansion_gets_its_own_row(self) -> None:
        """It is a distinct chunk of the prompt, so it is a row like anything else.

        A footnote does not let you compare it against the pins and turns around
        it, which is the whole job of the report.
        """
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[include: rules.grappling]: #\n",
            encoding="utf-8",
        )

        report = explain_context(self.session)
        block = _block(report, BLOCK_CURRENT)
        assert block is not None
        row = next(c for c in block.components if c.id == "include:rules.grappling")

        self.assertEqual(row.provenance_kind, "mention")
        self.assertIn("rest of this node", row.provenance)
        self.assertEqual(row.detail["scope"], "include")
        self.assertGreater(row.bytes, 0)
        self.assertEqual([i.kb_id for i in report.in_place], ["rules.grappling"])

    def test_splitting_keeps_the_block_arithmetic_exact(self) -> None:
        """Rows are pieces of the passage, not extra bytes bolted onto it."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[include: rules.grappling]: #\n",
            encoding="utf-8",
        )

        block = _block(explain_context(self.session), BLOCK_CURRENT)
        assert block is not None

        self.assertGreater(len(block.components), 1)
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_two_adjacent_mentions_each_get_a_row(self) -> None:
        """Two on consecutive lines is the natural shape of "I cast X and Y"."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[mention: rules.grappling]: #\n[mention: rules.cover]: #\n",
            encoding="utf-8",
        )

        block = _block(explain_context(self.session), BLOCK_CURRENT)
        assert block is not None
        rows = [c.id for c in block.components]

        self.assertIn("mention:rules.grappling", rows)
        self.assertIn("mention:rules.cover", rows)
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_rollup_agrees_with_the_rows(self) -> None:
        """Two numbers for the same object is how a report loses trust.

        A row absorbs the blank line separating it from its neighbour, so the
        roll-up has to come from the rows rather than be measured separately.
        """
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[mention: rules.grappling]: #\n[mention: rules.cover]: #\n",
            encoding="utf-8",
        )

        report = explain_context(self.session)
        rows = {
            c.detail["kb_id"]: c.bytes
            for b in report.blocks
            for c in b.components
            if c.provenance_kind == "mention"
        }

        self.assertEqual({i.kb_id: i.bytes for i in report.in_place}, rows)

    def test_expansion_row_appears_in_the_conversation_block_too(self) -> None:
        """Turns take a different path to the node text than the passage does."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[write]: #\n\nAmy walked on.\n\n[/write]: #\n"
            + "\n[include: rules.grappling]: #\n",
            encoding="utf-8",
        )

        block = _block(explain_context(self.session), BLOCK_CONVERSATION)
        assert block is not None

        self.assertIn("include:rules.grappling", [c.id for c in block.components])
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_no_row_once_a_mention_expires(self) -> None:
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[mention: rules.grappling]: #\n"
            + "\n[write]: #\n\nA turn passes.\n\n[/write]: #\n",
            encoding="utf-8",
        )

        self.assertEqual(explain_context(self.session).in_place, ())

    def test_inert_at_tokens_do_not_produce_a_warning(self) -> None:
        """Regression: prose full of `@ids` used to report them as unresolved."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\nAmy checks @rules.grappling and @spell.missing.\n",
            encoding="utf-8",
        )

        report = explain_context(self.session)

        self.assertEqual(
            [c for c in report.excluded if c.provenance_kind == "warning"], []
        )

    def test_rollup_ignores_mentions_that_are_not_spliced_in(self) -> None:
        """`mention-kb:` (state, diverted to the tail) and `mention-ref:` (node
        slices) also carry a "mention" provenance, but neither is inside the
        passage — listing them would double-count against their own block row
        and report an empty kind."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[mention: tracker.combat]: #\n",
            encoding="utf-8",
        )
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

        report = explain_context(self.session)

        # It is in scope, at the tail — but not as an in-place expansion.
        self.assertIn(
            BLOCK_STATE, [b.id for b in report.blocks]
        )
        self.assertEqual(report.in_place, ())
        self.assertTrue(all(i.kind in ("include", "mention") for i in report.in_place))

    def test_line_limited_report_suppresses_an_already_pinned_object(self) -> None:
        """`--line` must assemble the prompt the operator would, pins included."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[mention: person.amy]: #\n",
            encoding="utf-8",
        )
        line_count = len(path.read_text(encoding="utf-8").split("\n"))

        full = explain_context(self.session)
        limited = explain_context(self.session, line=line_count)

        # person.amy is pinned at the root in this fixture, so neither rendering
        # may expand it a second time inside the passage.
        self.assertEqual(full.in_place, ())
        self.assertEqual(limited.in_place, ())

    def test_row_survives_ai_secret_decoding(self) -> None:
        """The needle has to be transformed the way the passage was.

        Regression: a mentioned object carrying an `ai:secret` block reaches the
        model decoded, so an exact match against the emitted (encoded) block
        failed and the expansion silently vanished into the narrative row.
        """
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[mention: lore.bridge]: #\n",
            encoding="utf-8",
        )

        report = explain_context(self.session)
        block = _block(report, BLOCK_CURRENT)
        assert block is not None

        self.assertIn("mention:lore.bridge", [c.id for c in block.components])
        self.assertEqual([i.kb_id for i in report.in_place], ["lore.bridge"])
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_row_survives_mount_embed_stripping(self) -> None:
        """The other transform that rewrites a body — and it changes its length."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[mention: lore.map]: #\n",
            encoding="utf-8",
        )

        report = explain_context(self.session)
        block = _block(report, BLOCK_CURRENT)
        assert block is not None

        self.assertIn("mention:lore.map", [c.id for c in block.components])
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_a_rewritten_body_still_splits_alongside_a_plain_one(self) -> None:
        """Two expansions where only one needed transforming."""
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[mention: lore.bridge]: #\n\n[mention: rules.grappling]: #\n",
            encoding="utf-8",
        )

        block = _block(explain_context(self.session), BLOCK_CURRENT)
        assert block is not None
        rows = [c.id for c in block.components]

        self.assertIn("mention:lore.bridge", rows)
        self.assertIn("mention:rules.grappling", rows)
        self.assertEqual(
            sum(c.bytes for c in block.components) + block.framing_bytes, block.bytes
        )

    def test_knowledge_block_stays_out_of_it(self) -> None:
        path = self.cursor.md_path()
        path.write_text(
            path.read_text(encoding="utf-8") + "\n[include: rules.grappling]: #\n",
            encoding="utf-8",
        )
        report = explain_context(self.session)
        knowledge = _block(report, BLOCK_KNOWLEDGE)
        ids = [] if knowledge is None else [c.id for c in knowledge.components]
        self.assertNotIn("kb:rules.grappling", ids)
        self.assertNotIn("mention-kb:rules.grappling", ids)


class TestExplainIsReadOnly(ExplainTestCase):
    def test_leaves_the_working_tree_untouched(self) -> None:
        before = self.session.new_storage().pending_diff()
        explain_context(self.session)
        self.assertEqual(self.session.new_storage().pending_diff(), before)

    def test_does_not_claim_the_pending_transaction(self) -> None:
        explain_context(self.session)
        storage = self.session.new_storage()
        self.assertFalse(storage.has_staged())


class TestExplainOptions(ExplainTestCase):
    def test_operator_override_changes_the_assembled_prompt(self) -> None:
        default_report = explain_context(self.session)
        section_report = explain_context(self.session, operator="section")
        self.assertEqual(section_report.operator, "section")
        system_default = _block(default_report, BLOCK_SYSTEM)
        system_section = _block(section_report, BLOCK_SYSTEM)
        assert system_default is not None and system_section is not None
        self.assertNotEqual(system_default.bytes, system_section.bytes)

    def test_unknown_operator_is_rejected(self) -> None:
        with self.assertRaises(LensException) as ctx:
            explain_context(self.session, operator="not-an-operator")
        self.assertIn("unknown operator", str(ctx.exception))

    def test_unknown_sort_is_rejected(self) -> None:
        with self.assertRaises(LensException):
            explain_context(self.session, sort="sideways")

    def test_sort_size_orders_components_largest_first(self) -> None:
        report = explain_context(self.session, sort=SORT_SIZE)
        for block in report.blocks:
            sizes = [c.bytes for c in block.components]
            self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_prompt_is_folded_into_the_task_block(self) -> None:
        plain = explain_context(self.session)
        with_prompt = explain_context(
            self.session, prompt="describe the forest in detail"
        )
        task_plain = _block(plain, BLOCK_TASK)
        task_prompt = _block(with_prompt, BLOCK_TASK)
        assert task_plain is not None and task_prompt is not None
        self.assertGreater(task_prompt.bytes, task_plain.bytes)

    def test_line_truncates_the_current_passage(self) -> None:
        full = explain_context(self.session)
        truncated = explain_context(self.session, line=1)
        self.assertEqual(truncated.line, 1)
        current_full = _block(full, BLOCK_CURRENT)
        current_truncated = _block(truncated, BLOCK_CURRENT)
        assert current_full is not None
        self.assertTrue(
            current_truncated is None or current_truncated.bytes < current_full.bytes
        )

    def test_address_argument_targets_a_specific_node(self) -> None:
        narrative = self.session.active_narrative
        assert narrative is not None
        address = str(narrative.find_cursor().to_address())
        report = explain_context(self.session, address=address)
        self.assertEqual(report.address, address)

    def test_missing_node_is_rejected(self) -> None:
        with self.assertRaises(LensException):
            explain_context(self.session, address="/nope-does-not-exist")

    def test_chars_per_token_scales_the_estimate(self) -> None:
        four = explain_context(self.session, chars_per_token=4)
        two = explain_context(self.session, chars_per_token=2)
        self.assertGreater(two.total_tokens, four.total_tokens)


class TestExplainSerialization(ExplainTestCase):
    def test_to_dict_is_json_shaped(self) -> None:
        import json

        payload = explain_context(self.session).to_dict()
        json.dumps(payload)  # must not raise
        self.assertIn("blocks", payload)
        self.assertIn("totals", payload)
        self.assertEqual(
            payload["totals"]["bytes"],
            payload["totals"]["accounted_bytes"] + payload["totals"]["other_bytes"],
        )
        first_block = payload["blocks"][0]
        self.assertIn("components", first_block)
        self.assertIn("cache", first_block)


class TestExplainHelpers(unittest.TestCase):
    def test_estimate_tokens_rounds_up(self) -> None:
        self.assertEqual(estimate_tokens("", 4), 0)
        self.assertEqual(estimate_tokens("abc", 4), 1)
        self.assertEqual(estimate_tokens("abcd", 4), 1)
        self.assertEqual(estimate_tokens("abcde", 4), 2)

    def test_estimate_tokens_guards_against_zero_divisor(self) -> None:
        self.assertEqual(estimate_tokens("abcd", 0), 4)

    def test_conversation_block_id_is_stable(self) -> None:
        # The UI and API key off this id; changing it is a breaking change.
        self.assertEqual(BLOCK_CONVERSATION, "conversation")


class TestFacetsInTheReport(unittest.TestCase):
    """A `-` facet must be its own itemized, classified, counted row.

    Facets reach the prompt for `design`/`advance` only, and they arrive with
    their parent's pin origin — so the risk is that they are either invisible
    in the report or silently folded in with the pin that pulled them.
    """

    session: ProjectSession
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        cls.tmp = tempfile.mkdtemp(prefix="lens_explain_facets_")
        cls.session = setup_test_project(
            Path(cls.tmp), "http://127.0.0.1:1/v1", opening_write=False
        )
        store = KnowledgeStore.for_project(Path(cls.tmp))
        store.store_object(
            "person.amy-prep", "Prep material for Amy that play must not see."
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def _knowledge_rows(self, operator: str) -> dict[str, ExplainBlock]:
        report = explain_context(self.session, operator=operator)
        knowledge = _block(report, BLOCK_KNOWLEDGE)
        assert knowledge is not None
        return {c.id: c for c in knowledge.components}  # type: ignore[misc]

    def test_design_report_itemizes_the_facet(self) -> None:
        rows = self._knowledge_rows("design")
        self.assertIn("kb:person.amy-prep", rows)

    def test_facet_row_is_classified_as_a_facet(self) -> None:
        row = self._knowledge_rows("design")["kb:person.amy-prep"]
        self.assertEqual(row.provenance_kind, "facet")  # type: ignore[attr-defined]
        self.assertIn("person.amy", row.provenance)  # type: ignore[attr-defined]

    def test_facet_row_is_counted(self) -> None:
        row = self._knowledge_rows("design")["kb:person.amy-prep"]
        self.assertGreater(row.bytes, 0)  # type: ignore[attr-defined]
        self.assertGreater(row.tokens, 0)  # type: ignore[attr-defined]

    def test_parent_stays_a_node_pin(self) -> None:
        rows = self._knowledge_rows("design")
        self.assertEqual(rows["kb:person.amy"].provenance_kind, "node_pin")  # type: ignore[attr-defined]

    def test_write_report_has_no_facet_row(self) -> None:
        rows = self._knowledge_rows("write")
        self.assertIn("kb:person.amy", rows)
        self.assertNotIn("kb:person.amy-prep", rows)


class TestProvenance(unittest.TestCase):
    """``component_provenance`` maps graph components to a human 'why'."""

    @staticmethod
    def _component(cid: str, kind: ComponentKind, **metadata: str) -> CrawlComponent:
        return CrawlComponent(id=cid, kind=kind, text="x", metadata=dict(metadata))

    def _why(
        self,
        component: CrawlComponent,
        modality_pins: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        kind, why, _detail = component_provenance(
            component, operator_name="play", modality_pins=modality_pins or {}
        )
        return kind, why

    def test_node_pin(self) -> None:
        component = self._component(
            "kb:pc.elena",
            "knowledge",
            kb_id="pc.elena",
            pin_source="node",
            pin_node="story/chapter-1",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "node_pin")
        self.assertIn("story/chapter-1", why)

    def test_plus_expansion_names_the_parent(self) -> None:
        component = self._component(
            "kb:place.forest",
            "knowledge",
            kb_id="place.forest",
            pin_source="node",
            pin_node="story",
            pin_expanded_from="person.bob",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "expansion")
        self.assertIn("person.bob", why)

    def test_facet_names_the_parent(self) -> None:
        component = self._component(
            "kb:front.problem-prep",
            "knowledge",
            kb_id="front.problem-prep",
            pin_source="node",
            pin_node="story",
            facet_of="front.problem",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "facet")
        self.assertIn("front.problem", why)
        self.assertIn("story", why)

    def test_facet_is_not_reported_as_a_hand_written_pin(self) -> None:
        """A facet carries its parent's pin origin, so without a branch of its
        own it would read as a `kb_pin` the user typed."""
        component = self._component(
            "kb:front.problem-prep",
            "knowledge",
            kb_id="front.problem-prep",
            pin_source="node",
            pin_node="story",
            facet_of="front.problem",
        )
        kind, _why = self._why(component)
        self.assertNotEqual(kind, "node_pin")

    def test_facet_detail_carries_the_parent_id(self) -> None:
        component = self._component(
            "kb:front.problem-prep",
            "knowledge",
            kb_id="front.problem-prep",
            facet_of="front.problem",
        )
        _kind, _why, detail = component_provenance(
            component, operator_name="design", modality_pins={}
        )
        self.assertEqual(detail.get("facet_of"), "front.problem")

    def test_rules_companion(self) -> None:
        component = self._component(
            "rules-companion:rules.encounter", "knowledge", kb_id="rules.encounter"
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "rules_companion")
        self.assertIn("encounter", why)

    def test_mention_of_a_state_object(self) -> None:
        """The only mention shape that is a component rather than passage bytes."""
        component = self._component(
            "mention-kb:tracker.combat",
            "knowledge",
            kb_id="tracker.combat",
            mention_scope="state",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "mention")
        self.assertIn("tracker.combat", why)
        self.assertIn("tail", why)

    def test_session_module(self) -> None:
        component = self._component(
            "module:design.encounter",
            "knowledge",
            kb_id="design.encounter",
            module_role="module",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "module")
        self.assertIn("design.encounter", why)

    def test_module_link_names_the_module_it_came_from(self) -> None:
        component = self._component(
            "module:rules.system",
            "knowledge",
            kb_id="rules.system",
            module_role="module-link",
            module_linked_from="design.encounter",
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "module")
        self.assertIn("design.encounter", why)
        self.assertIn("+", why)

    def test_modality_pin_is_attributed_to_its_modality(self) -> None:
        component = self._component(
            "kb:rules.system", "knowledge", kb_id="rules.system", pin_source="extra"
        )
        kind, why = self._why(
            component, modality_pins={"rules.system": "rpg_play_context"}
        )
        self.assertEqual(kind, "modality")
        self.assertIn("rpg_play_context", why)

    def test_unattributed_extra_pin_falls_back_to_the_operator(self) -> None:
        component = self._component(
            "kb:pc.elena", "knowledge", kb_id="pc.elena", pin_source="extra"
        )
        kind, why = self._why(component)
        self.assertEqual(kind, "operator_pin")
        self.assertIn("play", why)


class TestReconciliationWithManyComponents(unittest.TestCase):
    """Rounding across many small components must not break the columns.

    Token counts are per-part ceilings, so a block full of small components
    accumulates rounding that a residual-derived framing figure would absorb
    (reporting framing that is really other rows' rounding, and going
    negative once the roundings outrun the wrapper). Both columns must still
    reconstruct the block exactly.
    """

    def test_columns_add_up_with_many_small_pins(self) -> None:
        import os

        from lens.core.commands.kb import kb_add
        from lens.core.commands.pin import pin_add

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        tmp = tempfile.mkdtemp(prefix="lens_explain_many_")
        try:
            session = setup_test_project(
                Path(tmp), "http://127.0.0.1:1/v1", opening_write=False
            )
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                for index in range(24):
                    kb_add(f"person.extra{index}", f"Tiny {index}.", False)
                    pin_add(session, f"person.extra{index}", None, [], None)
            finally:
                os.chdir(cwd)

            report = explain_context(session)
            knowledge = _block(report, BLOCK_KNOWLEDGE)
            assert knowledge is not None
            self.assertGreater(len(knowledge.components), 20)
            for block in report.blocks:
                self.assertGreaterEqual(block.framing_tokens, 0)
                self.assertEqual(
                    block.tokens,
                    sum(c.tokens for c in block.components) + block.framing_tokens,
                    f"block {block.id} token column does not add up",
                )
                self.assertEqual(
                    block.bytes,
                    sum(c.bytes for c in block.components) + block.framing_bytes,
                    f"block {block.id} byte column does not add up",
                )
            self.assertEqual(
                report.total_tokens,
                sum(b.tokens for b in report.blocks) + report.other_tokens,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()


class TestExpansionProvenanceEndToEnd(unittest.TestCase):
    """A real ``+`` pin must report the object it was expanded from."""

    def test_linked_object_is_marked_as_an_expansion(self) -> None:
        import os

        from lens.core.commands.kb import kb_add, kb_tag
        from lens.core.commands.pin import pin_add

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        tmp = tempfile.mkdtemp(prefix="lens_explain_expand_")
        try:
            session = setup_test_project(
                Path(tmp), "http://127.0.0.1:1/v1", opening_write=False
            )
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                kb_add("person.bob", "Bob the woodsman.", False)
                kb_tag("person.bob", ["place.forest"], [])
                pin_add(session, "person.bob+", None, [], None)
            finally:
                os.chdir(cwd)

            report = explain_context(session)
            knowledge = _block(report, BLOCK_KNOWLEDGE)
            assert knowledge is not None
            forest = next(
                c for c in knowledge.components if c.id == "kb:place.forest"
            )
            self.assertEqual(forest.provenance_kind, "expansion")
            self.assertIn("person.bob", forest.provenance)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()


class TestDetectOperator(ExplainTestCase):
    def test_detects_no_operator_on_a_plain_node(self) -> None:
        narrative = self.session.active_narrative
        assert narrative is not None
        self.assertIsNone(detect_operator_name(narrative.find_cursor()))


if __name__ == "__main__":
    unittest.main()


class TestExplainStateBlock(unittest.TestCase):
    """`state`-tagged objects are reported in their own volatile tail block."""

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self.tmp = tempfile.mkdtemp(prefix="lens_explain_state_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(KnowledgeStore.clear_registry)
        self.addCleanup(MediaService.clear_registry)
        self.session = setup_test_project(
            Path(self.tmp), "http://127.0.0.1:1/v1", opening_write=False
        )
        root = self.session.project_root
        kb = KnowledgeStore.for_project(root)
        kb.store_object("tracker.combat", "Goblin HP 7/7")
        kb.add_tags("tracker.combat", ["state"])
        narrative = self.session.active_narrative
        assert narrative is not None
        pin(
            narrative.find_cursor(),
            ["tracker.combat"],
            self.session.new_direct_edit_storage(),
        )
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def test_state_object_is_reported_outside_relevant_knowledge(self) -> None:
        report = explain_context(self.session)
        knowledge = _block(report, BLOCK_KNOWLEDGE)
        assert knowledge is not None
        self.assertNotIn(
            "kb:tracker.combat", {c.id for c in knowledge.components}
        )

        state = _block(report, BLOCK_STATE)
        assert state is not None
        tracker = next(c for c in state.components if c.id == "kb:tracker.combat")
        self.assertEqual(tracker.kind, "state")
        self.assertGreater(tracker.bytes, 0)

    def test_state_block_is_volatile_and_sits_just_before_the_task(self) -> None:
        report = explain_context(self.session)
        order = [b.id for b in report.blocks]
        self.assertEqual(order[order.index(BLOCK_STATE) + 1], BLOCK_TASK)
        state = _block(report, BLOCK_STATE)
        assert state is not None
        self.assertEqual(state.cache, "volatile")

    def test_totals_still_account_for_every_byte(self) -> None:
        report = explain_context(self.session)
        self.assertEqual(report.total_bytes, sum(report.message_bytes))
        self.assertEqual(
            report.accounted_bytes + report.other_bytes, report.total_bytes
        )
