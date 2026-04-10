from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.commands.stats import get_stats
from lens.core.context import crawl
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession


def _init_repo(tmp: Path) -> Path:
  import subprocess

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


def _make_project(tmp: Path, slug: str = "test") -> tuple[ProjectSession, NarrativeNode]:
  import subprocess

  (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
  narrative_dir = tmp / "narrative" / slug
  narrative_dir.mkdir(parents=True)
  (narrative_dir / "_node.md").write_text(f"# {slug}\n")
  kb_dir = tmp / "knowledge"
  kb_dir.mkdir(exist_ok=True)
  subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
  subprocess.run(
      ["git", "commit", "-m", "project"],
      cwd=tmp,
      capture_output=True,
      check=True,
  )
  return ProjectSession(tmp, tmp), NarrativeNode(narrative_root=narrative_dir, key_path=())


def _add_kb(root: Path, type_name: str, key: str, content: str) -> None:
  import subprocess

  path = root / "knowledge" / type_name / f"{key}.md"
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content)
  subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
  subprocess.run(
      ["git", "commit", "-m", f"kb {type_name}.{key}"],
      cwd=root,
      capture_output=True,
      check=True,
  )


class TestStatsEffectivePins(unittest.TestCase):
  def test_effective_pins_at_cursor_matches_crawl(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      _add_kb(root, "place", "a", "Place A")
      _add_kb(root, "place", "b", "Place B")

      root_node = node
      md = root_node.md_path()
      md.write_text(
          "[\n"
          "  kb_pin:\n"
          "    - place.a\n"
          "]: #\n\n"
          "# test\n"
      )
      (node.narrative_root / "ch1").mkdir()
      (node.narrative_root / "ch1" / "_node.md").write_text(
          "[\n"
          "  kb_pin:\n"
          "    - place.b\n"
          "]: #\n\n"
          "# ch1\n"
      )

      import subprocess

      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "pins"],
          cwd=root,
          capture_output=True,
          check=True,
      )

      # Point the active narrative cursor at the child node by appending an open
      # section annotation at the tail of the root node. Narrative.find_cursor
      # follows this open annotation into "ch1".
      narrative = session.active_narrative
      assert narrative is not None
      root_node = NarrativeNode(
          narrative_root=narrative.narrative_root,
          key_path=(),
      )
      md_root = root_node.md_path()
      md_root.write_text(
          md_root.read_text(encoding="utf-8") + "\n[section:ch1]: #\n"
      )
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "cursor"],
          cwd=root,
          capture_output=True,
          check=True,
      )

      result = get_stats(session)
      self.assertIsNotNone(result.cursor_addr)
      assert result.cursor_addr is not None
      cursor_node = result.cursor_addr.to_node(root)

      crawl_result = crawl(cursor_node)
      self.assertEqual(crawl_result.pinned_ids, result.effective_pins_at_cursor)
      self.assertEqual(result.effective_pins_at_cursor, ["place.a", "place.b"])


class TestStatsActiveSessionOperator(unittest.TestCase):
  def test_active_session_operator_chat_when_cursor_in_chat_subnode(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, _ = _make_project(root)

      narrative = session.active_narrative
      assert narrative is not None
      root_node = NarrativeNode(
          narrative_root=narrative.narrative_root,
          key_path=(),
      )
      (root_node.md_path().parent / "chat-bob-amy.md").write_text("# chat\n")
      md_root = root_node.md_path()
      md_root.write_text(
          md_root.read_text(encoding="utf-8").rstrip() + "\n\n[chat:chat-bob-amy]: #\n"
      )

      import subprocess

      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "chat session"],
          cwd=root,
          capture_output=True,
          check=True,
      )

      result = get_stats(session)
      self.assertEqual(result.active_session_operator, "chat")

