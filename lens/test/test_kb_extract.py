"""Tests for structured KB extraction (lens kb extract)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.kb import KbExtractEntry, parse_kb_fences, kb_extract
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore


def _make_project(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / "lens.toml").write_text("[project]\n")
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )


# ---------------------------------------------------------------------------
# Parser unit tests — no git required
# ---------------------------------------------------------------------------

class TestParseKbFences(unittest.TestCase):
    def _parse(self, text: str) -> tuple[list[KbExtractEntry], list[str]]:
        return parse_kb_fences(text)

    def test_single_block_with_tags(self) -> None:
        text = """\
```kb
---
id: person.alice
tags:
  - character
  - faction.rebels
---
Alice is a rebel fighter.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.id, "person.alice")
        self.assertEqual(e.tags, ["character", "faction.rebels"])
        self.assertEqual(e.content, "Alice is a rebel fighter.")

    def test_single_block_no_tags(self) -> None:
        text = """\
```kb
---
id: place.hq
---
The headquarters.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, "place.hq")
        self.assertEqual(entries[0].tags, [])
        self.assertEqual(entries[0].content, "The headquarters.")

    def test_two_blocks_with_ignored_text_between(self) -> None:
        text = """\
# Title

Some discussion text that should be ignored.

```kb
---
id: person.alice
---
Alice.
```

More ignored text here.

```kb
---
id: person.bob
---
Bob.
```

Trailing ignored text.
"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].id, "person.alice")
        self.assertEqual(entries[1].id, "person.bob")

    def test_html_comment_inside_content_preserved(self) -> None:
        text = """\
```kb
---
id: npc.hero
---
The hero<!-- ai:secret: has a dark past -->.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(entries[0].content, "The hero<!-- ai:secret: has a dark past -->.")

    def test_empty_content_block(self) -> None:
        text = """\
```kb
---
id: place.empty
---
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(entries[0].content, "")

    def test_missing_front_matter_dashes(self) -> None:
        text = """\
```kb
id: person.alice
Alice.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(entries, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("front matter", errors[0])

    def test_missing_id_field(self) -> None:
        text = """\
```kb
---
tags:
  - character
---
Content.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(entries, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("'id'", errors[0])

    def test_source_line_reported(self) -> None:
        text = """\
Line 1
Line 2
```kb
---
id: person.alice
---
Content.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(entries[0].source_line, 3)

    def test_no_kb_blocks(self) -> None:
        text = "Just a regular markdown file.\n\nNo kb blocks."
        entries, errors = self._parse(text)
        self.assertEqual(entries, [])
        self.assertEqual(errors, [])

    def test_valid_and_invalid_blocks_mixed(self) -> None:
        text = """\
```kb
---
id: person.good
---
Good block.
```

```kb
no front matter here
```

```kb
---
id: person.also-good
---
Also good.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(entries[0].id, "person.good")
        self.assertEqual(entries[1].id, "person.also-good")

    def test_multiline_content(self) -> None:
        text = """\
```kb
---
id: place.city
---
Line one.
Line two.
Line three.
```"""
        entries, errors = self._parse(text)
        self.assertEqual(errors, [])
        self.assertEqual(entries[0].content, "Line one.\nLine two.\nLine three.")


# ---------------------------------------------------------------------------
# Core integration tests — require a temp git project
# ---------------------------------------------------------------------------

class TestKbExtract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        KnowledgeStore.clear_registry()
        self._orig_dir = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self) -> None:
        os.chdir(self._orig_dir)
        shutil.rmtree(self.tmp, ignore_errors=True)
        KnowledgeStore.clear_registry()

    def _write_md(self, name: str, content: str) -> str:
        p = self.root / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_insert_single_object(self) -> None:
        path = self._write_md("objects.md", """\
```kb
---
id: person.alice
tags:
  - character
---
Alice is a rebel.
```
""")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.inserted, ["person.alice"])
        self.assertEqual(result.updated, [])
        obj_path = self.root / "knowledge" / "person" / "alice.md"
        self.assertTrue(obj_path.exists())
        self.assertEqual(obj_path.read_text(), "Alice is a rebel.")

    def test_insert_multiple_objects_single_transaction(self) -> None:
        path = self._write_md("bulk.md", """\
```kb
---
id: person.alice
---
Alice.
```

```kb
---
id: person.bob
---
Bob.
```
""")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        self.assertEqual(sorted(result.inserted), ["person.alice", "person.bob"])
        self.assertEqual(result.updated, [])
        self.assertTrue((self.root / "knowledge" / "person" / "alice.md").exists())
        self.assertTrue((self.root / "knowledge" / "person" / "bob.md").exists())

    def test_update_existing_object(self) -> None:
        # Pre-create an object
        kb = KnowledgeStore(self.root)
        kb.store_object("person.alice", "Old content.")
        # Commit it so it's not pending
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add alice"], cwd=self.root, capture_output=True, check=True)
        KnowledgeStore.clear_registry()

        path = self._write_md("update.md", """\
```kb
---
id: person.alice
---
New content.
```
""")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.inserted, [])
        self.assertEqual(result.updated, ["person.alice"])
        obj_path = self.root / "knowledge" / "person" / "alice.md"
        self.assertEqual(obj_path.read_text(), "New content.")

    def test_tags_written_to_tags_toml(self) -> None:
        path = self._write_md("tagged.md", """\
```kb
---
id: npc.hero
tags:
  - character
  - faction.order
---
The hero.
```
""")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        kb = KnowledgeStore(self.root)
        tags = kb.get_tags("npc.hero")
        self.assertIn("character", tags)
        self.assertIn("faction.order", tags)

    def test_tags_are_additive_on_update(self) -> None:
        # Pre-create with a tag
        kb = KnowledgeStore(self.root)
        kb.store_object("npc.hero", "Old.")
        kb.add_tags("npc.hero", ["existing-tag"])
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add hero"], cwd=self.root, capture_output=True, check=True)
        KnowledgeStore.clear_registry()

        path = self._write_md("update_tags.md", """\
```kb
---
id: npc.hero
tags:
  - new-tag
---
New content.
```
""")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        kb2 = KnowledgeStore(self.root)
        tags = kb2.get_tags("npc.hero")
        self.assertIn("existing-tag", tags)
        self.assertIn("new-tag", tags)

    def test_file_not_found_raises(self) -> None:
        with self.assertRaises(LensException) as ctx:
            kb_extract("/nonexistent/path/objects.md")
        self.assertIn("file not found", str(ctx.exception))

    def test_invalid_id_skipped_with_error(self) -> None:
        path = self._write_md("bad.md", """\
```kb
---
id: INVALID ID WITH SPACES
---
Content.
```

```kb
---
id: person.valid
---
Valid content.
```
""")
        result = kb_extract(path)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("invalid id", result.errors[0])
        self.assertEqual(result.inserted, ["person.valid"])

    def test_no_blocks_returns_empty_result(self) -> None:
        path = self._write_md("empty.md", "Just plain text, no kb blocks.")
        result = kb_extract(path)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.inserted, [])
        self.assertEqual(result.updated, [])

    def test_all_writes_are_pending_after_extract(self) -> None:
        """All changes should be unstaged (single pending transaction)."""
        path = self._write_md("multi.md", """\
```kb
---
id: person.alice
---
Alice.
```

```kb
---
id: person.bob
---
Bob.
```
""")
        kb_extract(path)
        # Check that changes are unstaged (pending)
        r = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=self.root, capture_output=True, text=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.root, capture_output=True, text=True,
        )
        all_pending = r.stdout.strip() + "\n" + untracked.stdout.strip()
        self.assertIn("alice.md", all_pending)
        self.assertIn("bob.md", all_pending)


if __name__ == "__main__":
    unittest.main()
