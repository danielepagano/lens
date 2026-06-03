"""Tests for the ``lens rewind`` command (core layer)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.rewind import rewind, rewind_to_line, rewind_to_node
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage


# ---------------------------------------------------------------------------
# Test-project helpers (same pattern used across the test suite)
# ---------------------------------------------------------------------------


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True,
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
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _commit_content(root: Path, node: NarrativeNode, content: str) -> None:
    node.md_path().write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "content"], cwd=root, capture_output=True, check=True,
    )



def _new_storage(root: Path) -> Storage:
    return Storage(root, owner=None)


# ---------------------------------------------------------------------------
# Helper: build a simple sibling tree under 'root_node'.
#
# Structure committed to git:
#
#   root/_node.md:
#       [section:b]: #
#       b summary
#       [/section:b]: #
#       [section:c]: #
#       c summary
#       [/section:c]: #
#       [section:d]: #
#       d summary
#       [/section:d]: #
#
#   root/b.md, root/c.md, root/d.md (each with a single content line)
# ---------------------------------------------------------------------------


def _setup_sibling_tree(
    root: Path, narrative: NarrativeNode
) -> tuple[NarrativeNode, NarrativeNode, NarrativeNode]:
    """Create sibling nodes b, c, d under *narrative*.  Return (b, c, d)."""
    nd = narrative.md_path().parent

    # Promote root to folder if it is still a leaf (_node.md already exists
    # because _make_project created it).
    b_md = nd / "b.md"
    c_md = nd / "c.md"
    d_md = nd / "d.md"

    b_md.write_text("b content\n", encoding="utf-8")
    c_md.write_text("c content\n", encoding="utf-8")
    d_md.write_text("d content\n", encoding="utf-8")

    root_content = (
        "[section:b]: #\n"
        "\n"
        "b summary\n"
        "\n"
        "[/section:b]: #\n"
        "[section:c]: #\n"
        "\n"
        "c summary\n"
        "\n"
        "[/section:c]: #\n"
        "[section:d]: #\n"
        "\n"
        "d summary\n"
        "\n"
        "[/section:d]: #\n"
    )
    narrative.md_path().write_text(root_content, encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "siblings"],
        cwd=root, capture_output=True, check=True,
    )

    return (
        narrative.child_node("b"),
        narrative.child_node("c"),
        narrative.child_node("d"),
    )


# ===========================================================================
# rewind_to_node tests
# ===========================================================================


class TestRewindToNodeSiblings(unittest.TestCase):
    """Rewind within a flat sibling structure."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)
        self.b, self.c, self.d = _setup_sibling_tree(self.root, self.narrative)

    def test_rewind_to_c_deletes_d_and_opens_c(self) -> None:
        storage = _new_storage(self.root)
        rewind_to_node(self.c, storage)

        # d node should be gone
        self.assertFalse(self.d.exists())

        # Root file should end with [section:c]: #  (open, no close tag)
        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:c]: #", root_text)
        self.assertNotIn("[/section:c]", root_text)
        self.assertNotIn("[section:d]", root_text)

        # b block should still be fully closed
        self.assertIn("[/section:b]: #", root_text)

        # c node should still exist and be untouched
        self.assertTrue(self.c.exists())
        self.assertEqual(self.c.md_path().read_text(), "c content\n")

        # find_cursor() should land on c
        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("c",))

    def test_rewind_to_b_deletes_c_and_d(self) -> None:
        storage = _new_storage(self.root)
        rewind_to_node(self.b, storage)

        self.assertFalse(self.c.exists())
        self.assertFalse(self.d.exists())

        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:b]: #", root_text)
        self.assertNotIn("[/section:b]", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("b",))

    def test_rewind_to_d_is_noop(self) -> None:
        """d is the last (closed) section; nothing after it → no-op."""
        storage = _new_storage(self.root)

        # The root has all sections closed, so find_cursor() returns root.
        # Rewinding to d re-opens d (deletes d's summary/close in root).
        rewind_to_node(self.d, storage)

        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:d]: #", root_text)
        self.assertNotIn("[/section:d]", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("d",))

    def test_rewind_to_root_with_all_closed_is_noop(self) -> None:
        """All sections closed → cursor is at root → rewind_to_node(root) = no-op."""
        storage = _new_storage(self.root)

        # Don't write anything — storage._ensure_ownership not triggered.
        # Just verify cursor is at root and stays there.
        cursor_before = self.narrative.find_cursor()
        self.assertEqual(cursor_before.key_path, ())

        rewind_to_node(self.narrative, storage)

        cursor_after = self.narrative.find_cursor()
        self.assertEqual(cursor_after.key_path, ())


class TestRewindToNodeOpenSection(unittest.TestCase):
    """Rewind when the target node has an open sub-section (cursor deeper)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_rewind_to_parent_cleans_open_child(self) -> None:
        """
        root/_node.md ends with [section:ch1]: # (open).
        ch1/_node.md ends with [section:scene1]: # (open).
        scene1.md has some content.

        Rewind to ch1 → scene1 is deleted, ch1's file is cleaned.
        """
        nd = self.narrative.md_path().parent
        (nd / "ch1").mkdir()
        (nd / "ch1" / "_node.md").write_text(
            "ch1 intro\n\n[section:scene1]: #\n", encoding="utf-8"
        )
        (nd / "ch1" / "scene1.md").write_text("scene1 content\n", encoding="utf-8")
        self.narrative.md_path().write_text(
            "[section:ch1]: #\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        ch1 = self.narrative.child_node("ch1")
        scene1 = ch1.child_node("scene1")

        storage = _new_storage(self.root)
        rewind_to_node(ch1, storage)

        # scene1 should be deleted
        self.assertFalse(scene1.exists())

        # ch1's file should no longer have [section:scene1]
        ch1_text = ch1.md_path().read_text()
        self.assertNotIn("[section:scene1]", ch1_text)

        # cursor lands on ch1
        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("ch1",))

    def test_rewind_to_root_cleans_open_section(self) -> None:
        """
        root/_node.md ends with [section:ch1]: # (open, cursor in ch1).
        Rewind to root → ch1 deleted.
        """
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1 content\n", encoding="utf-8")
        self.narrative.md_path().write_text(
            "preamble\n\n[section:ch1]: #\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        ch1 = self.narrative.child_node("ch1")

        storage = _new_storage(self.root)
        rewind_to_node(self.narrative, storage)

        self.assertFalse(ch1.exists())

        root_text = self.narrative.md_path().read_text()
        self.assertNotIn("[section:ch1]", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ())


class TestRewindToNodeDeepPath(unittest.TestCase):
    """Rewind to a node that is currently closed in its ancestors."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_rewind_reopens_closed_ancestor_chain(self) -> None:
        """
        root → ch1 (closed) → scene1 (closed)
        cursor is at root.

        Rewind to scene1 → both ch1 and scene1 are re-opened in their parents.
        """
        nd = self.narrative.md_path().parent
        (nd / "ch1").mkdir()
        (nd / "ch1" / "_node.md").write_text(
            "[section:scene1]: #\n\nscene1 summary\n\n[/section:scene1]: #\n",
            encoding="utf-8",
        )
        (nd / "ch1" / "scene1.md").write_text("scene1 content\n", encoding="utf-8")
        self.narrative.md_path().write_text(
            "[section:ch1]: #\n\nch1 summary\n\n[/section:ch1]: #\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        ch1 = self.narrative.child_node("ch1")
        scene1 = ch1.child_node("scene1")

        storage = _new_storage(self.root)
        rewind_to_node(scene1, storage)

        # root ends with [section:ch1]: # (open)
        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:ch1]: #", root_text)
        self.assertNotIn("[/section:ch1]", root_text)

        # ch1 ends with [section:scene1]: # (open)
        ch1_text = ch1.md_path().read_text()
        self.assertIn("[section:scene1]: #", ch1_text)
        self.assertNotIn("[/section:scene1]", ch1_text)

        # scene1 exists and is untouched
        self.assertTrue(scene1.exists())
        self.assertEqual(scene1.md_path().read_text(), "scene1 content\n")

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("ch1", "scene1"))

    def test_rewind_to_sibling_deletes_later_siblings_and_reopens_path(self) -> None:
        """
        root has a (closed), b (closed), c (open, cursor in c).
        Rewind to a → b and c deleted, a re-opened.
        """
        nd = self.narrative.md_path().parent
        for name in ("a", "b", "c"):
            (nd / f"{name}.md").write_text(f"{name} content\n", encoding="utf-8")

        self.narrative.md_path().write_text(
            "[section:a]: #\na summary\n[/section:a]: #\n"
            "[section:b]: #\nb summary\n[/section:b]: #\n"
            "[section:c]: #\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        a = self.narrative.child_node("a")
        b = self.narrative.child_node("b")
        c = self.narrative.child_node("c")

        storage = _new_storage(self.root)
        rewind_to_node(a, storage)

        self.assertFalse(b.exists())
        self.assertFalse(c.exists())
        self.assertTrue(a.exists())

        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:a]: #", root_text)
        self.assertNotIn("[/section:a]", root_text)
        self.assertNotIn("[section:b]", root_text)
        self.assertNotIn("[section:c]", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("a",))


class TestRewindToNodeErrors(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_nonexistent_node_raises(self) -> None:
        missing = self.narrative.child_node("nonexistent")
        storage = _new_storage(self.root)
        with self.assertRaises(LensException):
            rewind_to_node(missing, storage)

    def test_node_without_section_annotation_in_parent_raises(self) -> None:
        """Node exists on disk but parent has no matching [section:…] tag."""
        nd = self.narrative.md_path().parent
        (nd / "orphan.md").write_text("orphan\n", encoding="utf-8")
        # Root file has no [section:orphan] annotation
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "orphan"],
            cwd=self.root, capture_output=True, check=True,
        )

        orphan = self.narrative.child_node("orphan")
        storage = _new_storage(self.root)
        with self.assertRaises(LensException):
            rewind_to_node(orphan, storage)


# ===========================================================================
# rewind_to_line tests
# ===========================================================================


class TestRewindToLineFreeText(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_truncate_in_free_text(self) -> None:
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 3, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("line 3", result)
        self.assertNotIn("line 4", result)
        self.assertNotIn("line 5", result)

    def test_truncate_at_first_line(self) -> None:
        content = "line 1\nline 2\nline 3\n"
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 1, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("line 1", result)
        self.assertNotIn("line 2", result)

    def test_truncate_at_last_line_keeps_all(self) -> None:
        content = "only line\n"
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 1, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("only line", result)

    def test_line_out_of_range_raises(self) -> None:
        content = "one line\n"
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        with self.assertRaises(LensException):
            rewind_to_line(self.narrative, 99, storage)

    def test_free_text_truncation_deletes_later_section_child(self) -> None:
        """Truncating before a section annotation must also delete its child node."""
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1 content\n", encoding="utf-8")
        content = "line 1\nline 2\n[section:ch1]: #\n"
        _commit_content(self.root, self.narrative, content)

        ch1 = self.narrative.child_node("ch1")
        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 2, storage)

        self.assertFalse(ch1.exists())
        result = self.narrative.md_path().read_text()
        self.assertNotIn("[section:ch1]", result)

    def test_rewind_parent_line_before_long_chat_session_annotation(self) -> None:
        """Line rewind before a long session opener deletes the session child."""
        nd = self.narrative.md_path().parent
        (nd / "chat-awaken").mkdir()
        (nd / "chat-awaken" / "_node.md").write_text("chat turn\n", encoding="utf-8")
        preamble = [f"line {n}" for n in range(1, 16)]
        long_prompt = "You awaken. " + ("Long scene. It's very complicated. " * 100)
        content = (
            "\n".join(preamble)
            + "\n"
            + "[chat:chat-awaken\n"
            + "    as_kb_id: companion.eve\n"
            + f"    prompt: {long_prompt}\n"
            + "    reasoning: none\n"
            + "    with_kb_id: human.adam\n"
            + "]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        chat = self.narrative.child_node("chat-awaken")
        storage = _new_storage(self.root)
        rewind(self.narrative, 15, storage)

        self.assertFalse(chat.exists())
        result = self.narrative.md_path().read_text(encoding="utf-8")
        self.assertIn("line 15", result)
        self.assertNotIn("[chat:chat-awaken", result)


class TestRewindToLineFrontMatter(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_line_in_front_matter_clears_node(self) -> None:
        content = (
            "[\n"
            "    kb_pin:\n"
            "        - thing\n"
            "]: #\n"
            "\n"
            "Story content here.\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 2, storage)  # line 2 is inside front matter

        result = self.narrative.md_path().read_text()
        self.assertEqual(result, "")

    def test_line_in_front_matter_also_deletes_child_nodes(self) -> None:
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1\n", encoding="utf-8")
        content = (
            "[\n"
            "    kb_pin:\n"
            "        - thing\n"
            "]: #\n"
            "\n"
            "[section:ch1]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        ch1 = self.narrative.child_node("ch1")
        storage = _new_storage(self.root)
        rewind_to_line(self.narrative, 3, storage)

        self.assertFalse(ch1.exists())
        self.assertEqual(self.narrative.md_path().read_text(), "")


class TestRewindToLineAnnotationTag(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_line_inside_multiline_open_tag_deletes_annotation(self) -> None:
        content = (
            "preamble\n"
            "[write\n"
            "    prompt: hello\n"
            "]: #\n"
            "\n"
            "written content\n"
            "\n"
            "[/write]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        # Line 3 is "    prompt: hello" — inside the multiline write tag
        rewind_to_line(self.narrative, 3, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("preamble", result)
        self.assertNotIn("[write", result)
        self.assertNotIn("written content", result)

    def test_line_on_close_tag_keeps_it(self) -> None:
        content = (
            "[write]: #\n"
            "\n"
            "written content\n"
            "\n"
            "[/write]: #\n"
            "after\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        # Line 5 is "[/write]: #"
        rewind_to_line(self.narrative, 5, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("[/write]: #", result)
        self.assertNotIn("after", result)

    def test_line_on_section_open_tag_deletes_it_and_child(self) -> None:
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1 content\n", encoding="utf-8")
        content = "preamble\n[section:ch1]: #\n"
        _commit_content(self.root, self.narrative, content)

        ch1 = self.narrative.child_node("ch1")
        storage = _new_storage(self.root)
        # Line 2 is "[section:ch1]: #"
        rewind_to_line(self.narrative, 2, storage)

        self.assertFalse(ch1.exists())
        result = self.narrative.md_path().read_text()
        self.assertIn("preamble", result)
        self.assertNotIn("[section:ch1]", result)


class TestRewindToLineWriteBody(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_truncate_write_body_adds_close_tag(self) -> None:
        content = (
            "[write]: #\n"
            "\n"
            "line a\n"
            "line b\n"
            "line c\n"
            "\n"
            "[/write]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        # Line 4 is "line b"
        rewind_to_line(self.narrative, 4, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("[write]: #", result)
        self.assertIn("line b", result)
        self.assertNotIn("line c", result)
        self.assertIn("[/write]: #", result)

    def test_truncate_write_body_with_params(self) -> None:
        content = (
            "[write\n"
            "    prompt: continue\n"
            "]: #\n"
            "\n"
            "line a\n"
            "line b\n"
            "\n"
            "[/write]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        # Line 5 is "line a"
        rewind_to_line(self.narrative, 5, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("line a", result)
        self.assertNotIn("line b", result)
        # Close tag must be present (write always closes)
        self.assertIn("[/write]: #", result)

    def test_truncate_unclosed_write_body_adds_close_tag(self) -> None:
        """Write with no close tag yet (in-progress) — truncate should close it."""
        content = (
            "[write]: #\n"
            "\n"
            "line a\n"
            "line b\n"
            "line c\n"
        )
        _commit_content(self.root, self.narrative, content)

        storage = _new_storage(self.root)
        # Line 4 is "line b"
        rewind_to_line(self.narrative, 4, storage)

        result = self.narrative.md_path().read_text()
        self.assertIn("line b", result)
        self.assertNotIn("line c", result)
        self.assertIn("[/write]: #", result)


class TestRewindToLineSectionBody(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_line_in_section_summary_deletes_entire_section(self) -> None:
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1 content\n", encoding="utf-8")
        content = (
            "preamble\n"
            "[section:ch1]: #\n"
            "\n"
            "section summary line 1\n"
            "section summary line 2\n"
            "\n"
            "[/section:ch1]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        ch1 = self.narrative.child_node("ch1")
        storage = _new_storage(self.root)
        # Line 4 is "section summary line 1"
        rewind_to_line(self.narrative, 4, storage)

        # Section deleted entirely, child node deleted
        self.assertFalse(ch1.exists())
        result = self.narrative.md_path().read_text()
        self.assertIn("preamble", result)
        self.assertNotIn("[section:ch1]", result)
        self.assertNotIn("section summary", result)

    def test_line_in_section_summary_only_deletes_that_section_and_after(self) -> None:
        """Sections BEFORE the targeted one should be preserved."""
        nd = self.narrative.md_path().parent
        (nd / "a.md").write_text("a\n", encoding="utf-8")
        (nd / "b.md").write_text("b\n", encoding="utf-8")
        content = (
            "[section:a]: #\n"
            "a summary\n"
            "[/section:a]: #\n"
            "[section:b]: #\n"
            "b summary line 1\n"
            "[/section:b]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        a = self.narrative.child_node("a")
        b = self.narrative.child_node("b")
        storage = _new_storage(self.root)
        # Line 5 is "b summary line 1"
        rewind_to_line(self.narrative, 5, storage)

        self.assertTrue(a.exists())
        self.assertFalse(b.exists())

        result = self.narrative.md_path().read_text()
        self.assertIn("[/section:a]: #", result)
        self.assertNotIn("[section:b]", result)

    def test_line_in_open_section_body_deletes_section_and_child(self) -> None:
        """Cursor is inside a section (open, no close tag yet)."""
        nd = self.narrative.md_path().parent
        (nd / "ch1.md").write_text("ch1 content\n", encoding="utf-8")
        content = (
            "preamble\n"
            "[section:ch1]: #\n"
        )
        _commit_content(self.root, self.narrative, content)

        # Simulate being "inside" the open section body by adding content
        # to the root after the opening annotation.  The root file already
        # has just the open tag so there's no body yet — use line 2 (the tag).
        # Instead test with content after the tag (body of an open section):
        content2 = (
            "preamble\n"
            "[section:ch1]: #\n"
            "\n"
            "in-progress summary\n"
        )
        self.narrative.md_path().write_text(content2, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "body"],
            cwd=self.root, capture_output=True, check=True,
        )

        ch1 = self.narrative.child_node("ch1")
        storage = _new_storage(self.root)
        # Line 4 is "in-progress summary" — body of the open section
        rewind_to_line(self.narrative, 4, storage)

        self.assertFalse(ch1.exists())
        result = self.narrative.md_path().read_text()
        self.assertIn("preamble", result)
        self.assertNotIn("[section:ch1]", result)


class TestRewindToNodeFolderDeletion(unittest.TestCase):
    """Ensure folder nodes (with sub-directories) are deleted completely."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)

    def test_deletes_folder_node_recursively(self) -> None:
        """
        root has: intro (closed), ch1 (folder node with scene1 child, open = cursor).
        Rewind to intro → ch1 folder is recursively deleted.
        """
        nd = self.narrative.md_path().parent
        # intro is a simple leaf
        (nd / "intro.md").write_text("intro content\n", encoding="utf-8")
        # ch1 is a folder node with a sub-node scene1
        (nd / "ch1").mkdir()
        (nd / "ch1" / "_node.md").write_text(
            "[section:scene1]: #\nscene1 summary\n[/section:scene1]: #\n",
            encoding="utf-8",
        )
        (nd / "ch1" / "scene1.md").write_text("scene1\n", encoding="utf-8")
        self.narrative.md_path().write_text(
            "[section:intro]: #\nintro summary\n[/section:intro]: #\n"
            "[section:ch1]: #\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        intro = self.narrative.child_node("intro")
        ch1 = self.narrative.child_node("ch1")

        self.assertTrue(ch1.is_folder_node())
        self.assertTrue(ch1.child_node("scene1").exists())

        storage = _new_storage(self.root)
        rewind_to_node(intro, storage)

        # ch1 folder and all its contents should be gone
        self.assertFalse(ch1.exists())
        self.assertFalse((nd / "ch1").exists())
        # intro should still exist and be re-opened (no close tag)
        self.assertTrue(intro.exists())
        root_text = self.narrative.md_path().read_text()
        self.assertIn("[section:intro]: #", root_text)
        self.assertNotIn("[/section:intro]", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("intro",))


class TestRewindToTextInSection(unittest.TestCase):
    """Rewind to a specific text line inside a section: line rewind then node rewind."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.narrative = _make_project(tmp)
        nd = self.narrative.md_path().parent

        (nd / "a").mkdir()
        (nd / "a" / "_node.md").write_text(
            "text 2\n"
            "[section:a1]: #\n"
            "\n"
            "a1 summary\n"
            "\n"
            "[/section:a1]: #\n",
            encoding="utf-8",
        )
        (nd / "a" / "a1.md").write_text("text 3\n", encoding="utf-8")
        (nd / "b.md").write_text("b content\n", encoding="utf-8")

        self.narrative.md_path().write_text(
            "text 1\n"
            "[section:a]: #\n"
            "\n"
            "a summary\n"
            "\n"
            "[/section:a]: #\n"
            "text 4\n"
            "[section:b]: #\n"
            "\n"
            "b summary\n"
            "\n"
            "[/section:b]: #\n"
            "text 5\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "rewind-to-text setup"],
            cwd=self.root, capture_output=True, check=True,
        )

        self.section_a = self.narrative.child_node("a")
        self.section_a1 = self.section_a.child_node("a1")
        self.section_b = self.narrative.child_node("b")

    def test_rewind_to_text2_removes_a1_text3_and_main_tail_cursor_at_section_a(self) -> None:
        """
        main has: text 1, section a (closed), text 4, section b (closed), text 5; cursor at end.
        section a has: text 2, section a1 (closed); section a1 has text 3.

        Rewind to text 2: first truncate section a at line 1, then rewind to node section a.
        Assert: section a1 and text 3 deleted; text 4, section b, text 5 deleted from main;
        cursor at end of section a after text 2.
        """
        storage = _new_storage(self.root)
        rewind(self.section_a, 1, storage)

        self.assertFalse(self.section_a1.exists())
        self.assertFalse(self.section_b.exists())

        section_a_text = self.section_a.md_path().read_text()
        self.assertIn("text 2", section_a_text)
        self.assertNotIn("[section:a1]", section_a_text)
        self.assertNotIn("text 3", section_a_text)

        root_text = self.narrative.md_path().read_text()
        self.assertIn("text 1", root_text)
        self.assertIn("[section:a]: #", root_text)
        self.assertNotIn("[/section:a]", root_text)
        self.assertNotIn("text 4", root_text)
        self.assertNotIn("[section:b]", root_text)
        self.assertNotIn("text 5", root_text)

        cursor = self.narrative.find_cursor()
        self.assertEqual(cursor.key_path, ("a",))
