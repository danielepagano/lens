"""Unit tests for lens.core.mentions: annotation form, lifetime, in-place render."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.annotations import (
    parse_annotations,
    parse_tail_cursor_annotation,
    strip_markdown_comments,
)
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.mentions import (
    MENTION_LINE_RE,
    append_mention_annotations,
    build_mention_annotations,
    live_mentions,
    parse_mentions,
    render_mentions_in_place,
)
from lens.core.project import ProjectSession
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )
    return tmp


def _make_project(tmp: Path) -> Path:
    (tmp / "lens.toml").write_text('[project]\nnarrative = "test"\n')
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True
    )
    return tmp


def _add_kb(root: Path, kb_id: str, body: str, tags: list[str] | None = None) -> None:
    type_name, key = kb_id.split(".", 1)
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"kb {kb_id}"], cwd=root, capture_output=True, check=True
    )
    KnowledgeStore.clear_registry()
    MediaService.clear_registry()
    if tags:
        KnowledgeStore.for_project(root).add_tags(kb_id, tags)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()


class TestAnnotationForm(unittest.TestCase):
    def test_annotation_is_inert_to_the_rest_of_the_system(self) -> None:
        """The form has to be a plain markdown comment, not a Lens annotation.

        Otherwise it would show up as an operator, be mistaken for a cursor, and
        be counted against the auto-compress budget.
        """
        text = "prose\n[mention: spell.aid]: #\n[include: rules.grappling]: #\n"

        self.assertEqual(parse_annotations(text), [])
        self.assertIsNone(parse_tail_cursor_annotation(text))
        self.assertEqual(strip_markdown_comments(text).strip(), "prose")

    def test_one_line_per_distinct_id_in_first_occurrence_order(self) -> None:
        """A message naming several objects records one annotation each."""
        block = build_mention_annotations(
            "mention", ["spell.aid", "pc.rowan", "SPELL.AID", "spell.aid"]
        )

        self.assertEqual(block, "[mention: spell.aid]: #\n[mention: pc.rowan]: #")

    def test_no_ids_writes_nothing(self) -> None:
        self.assertEqual(build_mention_annotations("include", []), "")
        self.assertEqual(build_mention_annotations("include", ["  "]), "")

    def test_parse_reads_standalone_lines_and_annotation_params(self) -> None:
        text = (
            "> [Kira] I cast @spell.aid\n"
            "[mention: spell.aid]: #\n"
            "[include: rules.grappling]: #\n"
            "\n"
            "[write\n"
            "    prompt: more\n"
            "    mention:\n"
            "    - person.amy\n"
            "]: #\n"
        )

        self.assertEqual(
            [(r.kind, r.kb_id, r.line) for r in parse_mentions(text)],
            [
                ("mention", "spell.aid", 2),
                ("include", "rules.grappling", 3),
                ("mention", "person.amy", 5),
            ],
        )


def assert_annotations_start_a_block(text: str) -> None:
    """Every annotation line must be preceded by a blank line or start the file.

    This is the property markdown cares about: a reference-style comment is only
    consumed as a link definition when it *starts* a block.  Written straight
    under a line of prose it becomes a lazy continuation of that paragraph, and
    the reader sees ``[mention: spell.aid]: #`` sitting in the story.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not MENTION_LINE_RE.match(line):
            continue
        prev = lines[i - 1] if i else ""
        opens_block = i == 0 or prev.strip() == "" or bool(MENTION_LINE_RE.match(prev))
        assert opens_block, (
            f"line {i + 1} {line!r} follows {prev!r} with no blank line — "
            "markdown will render it as visible prose"
        )


class TestAnnotationsAreWrittenAsTheirOwnBlock(unittest.TestCase):
    """Regression: mentions glued under a player line leaked into the page."""

    def test_after_prose(self) -> None:
        out = append_mention_annotations(
            "> [Kira] I cast @spell.aid\n", {"mention": ["spell.aid"]}
        )
        assert_annotations_start_a_block(out)
        self.assertEqual(
            out, "> [Kira] I cast @spell.aid\n\n[mention: spell.aid]: #\n"
        )

    def test_after_prose_with_no_trailing_newline(self) -> None:
        out = append_mention_annotations("Some prose.", {"mention": ["spell.aid"]})
        assert_annotations_start_a_block(out)

    def test_does_not_stack_blank_lines(self) -> None:
        out = append_mention_annotations("Prose.\n\n", {"mention": ["spell.aid"]})
        assert_annotations_start_a_block(out)
        self.assertEqual(out, "Prose.\n\n[mention: spell.aid]: #\n")

    def test_at_the_start_of_an_empty_node(self) -> None:
        out = append_mention_annotations("", {"include": ["rules.grappling"]})
        assert_annotations_start_a_block(out)
        self.assertEqual(out, "[include: rules.grappling]: #\n")

    def test_several_kinds_stay_one_block(self) -> None:
        out = append_mention_annotations(
            "Prose.\n", {"mention": ["a.one", "b.two"], "include": ["c.three"]}
        )
        assert_annotations_start_a_block(out)
        self.assertEqual(
            out,
            "Prose.\n\n[mention: a.one]: #\n[mention: b.two]: #\n"
            "[include: c.three]: #\n",
        )

    def test_nothing_to_write_leaves_the_text_alone(self) -> None:
        self.assertEqual(append_mention_annotations("Prose.\n", {}), "Prose.\n")

    def test_appending_twice_stays_well_formed(self) -> None:
        out = append_mention_annotations("Prose.\n", {"mention": ["a.one"]})
        out = append_mention_annotations(out, {"include": ["b.two"]})
        assert_annotations_start_a_block(out)


class TestAnnotationsDoNotMaskTheCursor(unittest.TestCase):
    """Regression: a trailing mention silently moved the cursor out of a session.

    "Inert" has to mean the tail scan *skips* these lines.  A scan that merely
    fails to recognise one reports no open annotation, so `find_cursor` stops
    descending and the open section/play/chat is abandoned — while
    `find_unclosed_cursor_annotation`, which parses segments instead, still sees
    it.  The two disagreeing is worse than either answer.
    """

    OPEN = "# s\n\nStory.\n\n[section:chapter-1]: #\n"

    def _both(self, text: str) -> tuple[str | None, str | None]:
        from lens.core.narrative import find_unclosed_cursor_annotation

        tail = parse_tail_cursor_annotation(text)
        unclosed = find_unclosed_cursor_annotation(text)
        return (tail.id if tail else None, unclosed.id if unclosed else None)

    def test_open_session_is_still_found_under_a_mention(self) -> None:
        self.assertEqual(self._both(self.OPEN + "\n[mention: a.b]: #\n"), ("chapter-1", "chapter-1"))

    def test_open_session_is_still_found_under_several(self) -> None:
        text = self.OPEN + "\n[mention: a.b]: #\n[include: c.d]: #\n\n"
        self.assertEqual(self._both(text), ("chapter-1", "chapter-1"))

    def test_a_closed_session_stays_closed(self) -> None:
        text = "# s\n\n[section:ch]: #\n\ntext\n\n[/section:ch]: #\n\n[mention: a.b]: #\n"
        self.assertEqual(self._both(text), (None, None))

    def test_both_scanners_agree_with_and_without_the_annotation(self) -> None:
        self.assertEqual(self._both(self.OPEN), self._both(self.OPEN + "\n[include: c.d]: #\n"))


class TestPinScopedTargeting(unittest.TestCase):
    """`pin kb mention|include` writing into a node other than the cursor."""

    def _project(self, tmp: Path) -> ProjectSession:
        root = _make_project(_init_repo(tmp))
        (root / "lens.toml").write_text('[project]\nnarrative = "s"\n')
        nd = root / "narrative" / "s" / "chapter-1"
        nd.mkdir(parents=True)
        (root / "narrative" / "s" / "_node.md").write_text(
            "# s\n\nStory.\n\n[section:chapter-1]: #\n"
        )
        (nd / "_node.md").write_text("# chapter one\n\nHere.\n")
        _add_kb(root, "spell.aid", "Aid.")
        return ProjectSession(git_root=root, project_root=root)

    def test_reports_when_the_target_is_not_the_cursor(self) -> None:
        from lens.core.commands.pin import pin_scoped

        with tempfile.TemporaryDirectory() as tmp:
            session = self._project(Path(tmp))
            narrative = session.active_narrative
            assert narrative is not None
            self.assertEqual(narrative.find_cursor().key_path, ("chapter-1",))

            _, target, applies_now = pin_scoped(
                session, "mention", "spell.aid", "s", [], None
            )

            self.assertEqual(target, "s")
            self.assertFalse(applies_now)

    def test_writing_into_an_ancestor_does_not_move_the_cursor(self) -> None:
        """The annotation must not mask the open section above it."""
        from lens.core.commands.pin import pin_scoped

        with tempfile.TemporaryDirectory() as tmp:
            session = self._project(Path(tmp))
            pin_scoped(session, "mention", "spell.aid", "s", [], None)

            narrative = session.active_narrative
            assert narrative is not None
            self.assertEqual(narrative.find_cursor().key_path, ("chapter-1",))

    def test_cursor_target_applies_now(self) -> None:
        from lens.core.commands.pin import pin_scoped

        with tempfile.TemporaryDirectory() as tmp:
            session = self._project(Path(tmp))

            _, target, applies_now = pin_scoped(
                session, "include", "spell.aid", None, [], None
            )

            self.assertEqual(target, "s / chapter-1")
            self.assertTrue(applies_now)

    def test_missing_node_is_a_clean_error_not_a_traceback(self) -> None:
        from lens.core.commands.pin import pin_scoped
        from lens.core.exceptions import LensException

        with tempfile.TemporaryDirectory() as tmp:
            session = self._project(Path(tmp))

            with self.assertRaises(LensException) as ctx:
                pin_scoped(session, "mention", "spell.aid", "s/nope", [], None)

            self.assertIn("does not exist", str(ctx.exception))


class TestLifetime(unittest.TestCase):
    def test_mention_is_live_until_an_assistant_turn_follows_it(self) -> None:
        before = "> [Kira] I cast @spell.aid\n[mention: spell.aid]: #\n"
        after = before + "\n[play]: #\n\nThe aid takes hold.\n\n[/play]: #\n"

        self.assertEqual([r.kb_id for r in live_mentions(before)], ["spell.aid"])
        self.assertEqual(live_mentions(after), [])

    def test_include_never_expires(self) -> None:
        text = (
            "[include: rules.grappling]: #\n"
            "\n[play]: #\n\nturn one\n\n[/play]: #\n"
            "\n[play]: #\n\nturn two\n\n[/play]: #\n"
        )

        self.assertEqual([r.kb_id for r in live_mentions(text)], ["rules.grappling"])

    def test_retry_does_not_consume_a_mention(self) -> None:
        """`write_discard` truncates to the open tag, so nothing counts yet.

        There is no counter to consume — liveness is distance to the cursor, and
        the turn being regenerated is not in the text during the retry.
        """
        discarded = (
            "intro\n\n[write\n    prompt: tell me\n    mention:\n"
            "    - person.amy\n]: #\n"
        )

        self.assertEqual([r.kb_id for r in live_mentions(discarded)], ["person.amy"])

    def test_expired_annotation_stays_in_the_text(self) -> None:
        """Expiry is a render decision; rewinding past it restores the mention."""
        expired = (
            "[mention: spell.aid]: #\n\n[play]: #\n\nreply\n\n[/play]: #\n"
        )

        self.assertEqual([r.kb_id for r in parse_mentions(expired)], ["spell.aid"])
        self.assertEqual(live_mentions(expired), [])

    def test_a_summary_turn_does_not_expire_a_mention(self) -> None:
        """Only assistant turns count; an id-carrying pair is a user summary."""
        text = (
            "[mention: spell.aid]: #\n\n[section:ch1]: #\n\nsummary\n\n[/section:ch1]: #\n"
        )

        self.assertEqual([r.kb_id for r in live_mentions(text)], ["spell.aid"])


class TestRenderInPlace(unittest.TestCase):
    def _storage(self, root: Path) -> Storage:
        return Storage(root)

    def test_expands_at_the_annotation_line_not_in_a_knowledge_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "spell.aid", "Aid raises hit point maximums.")
            raw = (
                "> [Kira] I cast @spell.aid\n"
                "[mention: spell.aid]: #\n"
                "> [GM] Roll it.\n"
            )

            out, state_ids, _ = render_mentions_in_place(
                raw, project_root=root, storage=self._storage(root)
            )

            self.assertEqual(state_ids, [])
            lines = out.split("\n")
            self.assertEqual(lines[0], "> [Kira] I cast @spell.aid")
            # Blank line, so the block is its own unit rather than a lazy
            # continuation of the sentence above it.
            self.assertEqual(lines[1], "")
            self.assertEqual(lines[2], "KB['spell.aid']")
            self.assertEqual(lines[3], "Aid raises hit point maximums.")
            self.assertEqual(lines[4], "")
            # The prose after the mention is untouched and still follows it.
            self.assertIn("> [GM] Roll it.", out)

    def test_appending_a_mention_leaves_everything_before_it_byte_identical(self) -> None:
        """The whole point: expansion is append-only, so the prefix still caches."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "spell.aid", "Aid raises hit point maximums.")
            storage = self._storage(root)
            first = "> [Kira] Hello\n"
            second = first + "> [Kira] I cast it\n[mention: spell.aid]: #\n"

            before, _, _ = render_mentions_in_place(
                first, project_root=root, storage=storage
            )
            after, _, _ = render_mentions_in_place(
                second, project_root=root, storage=storage
            )

            self.assertTrue(after.startswith(before.rstrip("\n")))

    def test_expired_mention_expands_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "spell.aid", "Aid raises hit point maximums.")
            raw = "[mention: spell.aid]: #\n\n[play]: #\n\nreply\n\n[/play]: #\n"

            out, _, _ = render_mentions_in_place(
                raw, project_root=root, storage=self._storage(root)
            )

            self.assertEqual(out, raw)
            self.assertNotIn("KB['spell.aid']", out)

    def test_already_pinned_object_is_not_expanded_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "spell.aid", "Aid raises hit point maximums.")
            raw = "[mention: spell.aid]: #\n"

            out, _, _ = render_mentions_in_place(
                raw,
                project_root=root,
                storage=self._storage(root),
                pinned_ids=["spell.aid"],
            )

            self.assertEqual(out, raw)

    def test_an_include_suppresses_a_later_mention_of_the_same_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "rules.grappling", "Grappling rules body.")
            raw = (
                "[include: rules.grappling]: #\n"
                "> [Kira] again\n"
                "[mention: rules.grappling]: #\n"
            )

            out, _, _ = render_mentions_in_place(
                raw, project_root=root, storage=self._storage(root)
            )

            self.assertEqual(out.count("KB['rules.grappling']"), 1)

    def test_pending_mention_renders_at_end_of_text(self) -> None:
        """Covers the one turn where the annotation is not persisted yet."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person.amy", "Amy the merchant.")
            from lens.core.mentions import MentionRef

            out, _, _ = render_mentions_in_place(
                "existing prose\n",
                project_root=root,
                storage=self._storage(root),
                pending=[MentionRef(kind="mention", kb_id="person.amy", line=10**6)],
            )

            self.assertTrue(out.startswith("existing prose\n"))
            self.assertIn("KB['person.amy']", out)
            self.assertLess(out.index("existing prose"), out.index("KB['person.amy']"))

    def test_state_tagged_object_is_deferred_not_inlined(self) -> None:
        """Mutable content must not be frozen into the append-only transcript."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "tracker.combat", "Goblin HP 7/7", tags=["state"])
            raw = "[mention: tracker.combat]: #\n"

            out, state_ids, _ = render_mentions_in_place(
                raw, project_root=root, storage=self._storage(root)
            )

            self.assertEqual(state_ids, ["tracker.combat"])
            self.assertNotIn("KB['tracker.combat']", out)

    def test_unknown_id_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            raw = "[mention: npc.ghost]: #\n"

            out, state_ids, _ = render_mentions_in_place(
                raw, project_root=root, storage=self._storage(root)
            )

            self.assertEqual(out, raw)
            self.assertEqual(state_ids, [])


if __name__ == "__main__":
    unittest.main()
