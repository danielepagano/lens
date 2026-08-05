from __future__ import annotations

import os
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


def _write_kb_tags_toml(root: Path, objects: dict[str, list[str]]) -> None:
  import json
  import subprocess

  lines = ["[objects]"]
  for oid, tags in sorted(objects.items()):
    tag_repr = ", ".join(json.dumps(t) for t in tags)
    lines.append(f"{json.dumps(oid)} = [{tag_repr}]")
  (root / "knowledge" / "tags.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
  subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
  subprocess.run(
      ["git", "commit", "-m", "tags"],
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

  def test_remember_pins_at_cursor_maps_remember_dot_tags(self) -> None:
    from lens.core.knowledge import KnowledgeStore
    from lens.core.media import MediaService

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      _add_kb(root, "place", "a", "Place A")
      _add_kb(root, "place", "b", "Place B")

      md = node.md_path()
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

      narrative = session.active_narrative
      assert narrative is not None
      root_only = NarrativeNode(
          narrative_root=narrative.narrative_root,
          key_path=(),
      )
      md_root = root_only.md_path()
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

      _write_kb_tags_toml(
          root,
          {"place.b": ["remember.session-notes", "featured"]},
      )
      KnowledgeStore.clear_registry()
      MediaService.clear_registry()

      result = get_stats(session)
      self.assertEqual(result.remember_pins_at_cursor, {"place.b": ["remember.session-notes"]})


class TestStatsEffectiveVarsAndParams(unittest.TestCase):
  def test_effective_vars_inherited_at_cursor(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text('[project]\nnarrative = "t"\n', encoding="utf-8")
      narrative_dir = root / "narrative" / "t"
      narrative_dir.mkdir(parents=True)
      (narrative_dir / "_node.md").write_text(
          "[\n"
          "  vars:\n"
          "    mood: root_mood\n"
          "]: #\n\n"
          "# root\n",
          encoding="utf-8",
      )
      (narrative_dir / "ch1").mkdir()
      (narrative_dir / "ch1" / "_node.md").write_text(
          "[\n"
          "  vars:\n"
          "    mood: leaf_mood\n"
          "]: #\n\n"
          "# ch1\n",
          encoding="utf-8",
      )
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "tree"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      narrative = session.active_narrative
      assert narrative is not None
      root_node = NarrativeNode(
          narrative_root=narrative.narrative_root,
          key_path=(),
      )
      md_root = root_node.md_path()
      md_root.write_text(
          md_root.read_text(encoding="utf-8").rstrip() + "\n\n[section:ch1]: #\n",
          encoding="utf-8",
      )
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "cursor"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      result = get_stats(session)
      self.assertEqual(result.effective_vars_at_cursor, {"mood": "leaf_mood"})

  def test_effective_params_global_from_lens_toml(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
          '[project]\nnarrative = "t"\n\n[params.global]\nllm_id = "from_toml"\n',
          encoding="utf-8",
      )
      narrative_dir = root / "narrative" / "t"
      narrative_dir.mkdir(parents=True)
      (narrative_dir / "_node.md").write_text("# leaf\n", encoding="utf-8")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "project"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      result = get_stats(session)
      self.assertEqual(result.effective_params_at_cursor.get("global:llm_id"), "from_toml")


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

  def test_effective_pins_include_chat_as_with(self) -> None:
    """Cursor in a chat sub-node: stats list as/with from parent annotation."""
    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      _add_kb(root, "npc", "bob", "Bob")
      _add_kb(root, "pc", "amy", "Amy")

      slug = "chat-sess"
      root_md = node.md_path()
      root_md.write_text(
          f"# test\n\n[chat:{slug}\n"
          "    as_kb_id: npc.bob\n"
          "    with_kb_id: pc.amy\n"
          "]: #\n"
      )
      sess_dir = node.narrative_root / slug
      sess_dir.mkdir()
      (sess_dir / "_node.md").write_text(f"# {slug}\n")

      import subprocess

      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "chat session"],
          cwd=root,
          capture_output=True,
          check=True,
      )

      result = get_stats(session)
      pins = result.effective_pins_at_cursor
      self.assertIn("npc.bob", pins)
      self.assertIn("pc.amy", pins)

  def test_effective_params_keep_pinned_chat_overrides_in_chat_child(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
          '[project]\nnarrative = "test"\n\n[params.global]\nllm_id = "from_toml"\n',
          encoding="utf-8",
      )
      narrative_dir = root / "narrative" / "test"
      narrative_dir.mkdir(parents=True)
      (root / "knowledge").mkdir(exist_ok=True)
      slug = "chat-sess"
      (narrative_dir / "_node.md").write_text(
          "[\n"
          "  params:\n"
          "    chat:\n"
          "      as_kb_id: npc.pinned\n"
          "      with_kb_id: pc.pinned\n"
          "]: #\n\n"
          f"[chat:{slug}\n"
          "    as_kb_id: npc.session\n"
          "    with_kb_id: pc.session\n"
          "]: #\n",
          encoding="utf-8",
      )
      sess_dir = narrative_dir / slug
      sess_dir.mkdir()
      (sess_dir / "_node.md").write_text(f"# {slug}\n", encoding="utf-8")

      import subprocess

      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "chat session"],
          cwd=root,
          capture_output=True,
          check=True,
      )

      result = get_stats(ProjectSession(root, root))
      self.assertEqual(
          result.effective_params_at_cursor,
          {
              "chat:as_kb_id": "npc.pinned",
              "chat:with_kb_id": "pc.pinned",
              "global:llm_id": "from_toml",
          },
      )


class TestStatsImageDefaults(unittest.TestCase):
  def test_image_defaults_from_first_image_block(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
        '[project]\n'
        'narrative = "story"\n\n'
        '[[image]]\n'
        'api = "a2e"\n'
        'model = "a2e"\n'
        'api_key_env = "FAKE_IMG_KEY"\n'
        'aspect_ratios = ["16:9", "1:1"]\n'
        'sizes = ["2k", "1k"]\n'
        'max_batch = 4\n'
      )
      story = root / "narrative" / "story"
      story.mkdir(parents=True)
      (story / "_node.md").write_text("# story\n")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "proj"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      result = get_stats(session)
      self.assertEqual(len(result.image_backends), 1)
      row = result.image_backends[0]
      self.assertEqual(row["id"], "[default]")
      self.assertEqual(row["aspect_ratios"], ["16:9", "1:1"])
      self.assertEqual(row["sizes"], ["2k", "1k"])
      self.assertEqual(row["default_aspect"], "16:9")
      self.assertEqual(row["default_size"], "2k")
      self.assertEqual(row["default_batch"], 1)
      self.assertEqual(row["max_batch"], 4)
      self.assertTrue(row["supports_reference_images"])
      self.assertTrue(result.reference_images_supported)

  def test_image_backends_lists_all_valid_blocks(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
        '[project]\n'
        'narrative = "story"\n\n'
        '[[image]]\n'
        'id = "fast"\n'
        'api = "a2e"\n'
        'model = "a2e"\n'
        'api_key_env = "FAKE_IMG_KEY"\n'
        'aspect_ratios = ["16:9"]\n'
        'sizes = ["2k"]\n'
        'max_batch = 2\n\n'
        '[[image]]\n'
        'id = "square"\n'
        'api = "a2e"\n'
        'model = "a2e"\n'
        'api_key_env = "FAKE_IMG_KEY"\n'
        'aspect_ratios = ["1:1", "4:3"]\n'
        'sizes = ["1k"]\n'
        'max_batch = 8\n'
      )
      story = root / "narrative" / "story"
      story.mkdir(parents=True)
      (story / "_node.md").write_text("# story\n")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "proj"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      result = get_stats(session)
      self.assertEqual([b["id"] for b in result.image_backends], ["fast", "square"])
      self.assertEqual(result.image_backends[1]["aspect_ratios"], ["1:1", "4:3"])


class TestStatsTtsAvailable(unittest.TestCase):
  def test_false_without_mount_or_speech(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, _ = _make_project(root)
      result = get_stats(session)
      self.assertFalse(result.tts_available)

  def test_false_mount_only(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "media"\n')
      story = root / "narrative" / "story"
      story.mkdir(parents=True)
      (story / "_node.md").write_text("# story\n")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "proj"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      result = get_stats(session)
      self.assertTrue(result.has_mount)
      self.assertFalse(result.tts_available)

  def test_false_speech_only(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
          '[project]\n'
          'narrative = "story"\n\n'
          '[[speech]]\n'
          'api = "xai"\n'
          'api_key_env = "STAT_TTS_ONLY_KEY"\n'
      )
      story = root / "narrative" / "story"
      story.mkdir(parents=True)
      (story / "_node.md").write_text("# story\n")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "proj"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      os.environ["STAT_TTS_ONLY_KEY"] = "secret"
      try:
        result = get_stats(session)
      finally:
        os.environ.pop("STAT_TTS_ONLY_KEY", None)
      self.assertFalse(result.has_mount)
      self.assertFalse(result.tts_available)

  def test_true_mount_and_resolvable_speech(self) -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      (root / "lens.toml").write_text(
          '[project]\n'
          'narrative = "story"\n'
          'mount_point = "media"\n\n'
          '[[speech]]\n'
          'api = "xai"\n'
          'api_key_env = "STAT_TTS_OK_KEY"\n'
      )
      story = root / "narrative" / "story"
      story.mkdir(parents=True)
      (story / "_node.md").write_text("# story\n")
      (root / "knowledge").mkdir(exist_ok=True)
      subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "proj"],
          cwd=root,
          capture_output=True,
          check=True,
      )
      session = ProjectSession(root, root)
      os.environ["STAT_TTS_OK_KEY"] = "secret"
      try:
        result = get_stats(session)
      finally:
        os.environ.pop("STAT_TTS_OK_KEY", None)
      self.assertTrue(result.has_mount)
      self.assertTrue(result.tts_available)


class TestStatsModalities(unittest.TestCase):
  def tearDown(self) -> None:
    from lens.core.modalities import clear_registry_for_tests

    clear_registry_for_tests()

  def test_registered_and_active_modalities_at_cursor(self) -> None:
    from unittest.mock import patch

    from lens.core.modalities import Modality, clear_registry_for_tests, register_modality
    from lens.core.pinning import set_modality
    from lens.core.storage import Storage

    class _StatsBuiltin(Modality):
      id = "stats_builtin_test"
      builtin = True

    clear_registry_for_tests()
    register_modality(_StatsBuiltin())

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      with patch("lens.core.commands.stats.ensure_modalities_registered"):
        result = get_stats(session)
      self.assertEqual(result.registered_modality_ids, ["stats_builtin_test"])
      self.assertEqual(result.modalities_at_cursor, ["stats_builtin_test"])
      self.assertEqual(result.modality_warnings_at_cursor, [])

      set_modality(node, "stats_builtin_test", False, Storage(root))
      with patch("lens.core.commands.stats.ensure_modalities_registered"):
        result = get_stats(session)
      self.assertEqual(result.modalities_at_cursor, [])

  def test_unknown_fm_modality_warns(self) -> None:
    from lens.core.pinning import set_modality
    from lens.core.storage import Storage

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      set_modality(node, "not_a_real_modality", True, Storage(root))
      result = get_stats(session)
      self.assertIn("unknown modality 'not_a_real_modality'", result.modality_warnings_at_cursor)

  def test_effective_modalities_at_cursor_reflects_raw_fm_config(self) -> None:
    from lens.core.pinning import set_modality, set_modality_config
    from lens.core.storage import Storage

    with tempfile.TemporaryDirectory() as tmpdir:
      root = _init_repo(Path(tmpdir))
      session, node = _make_project(root)
      storage = Storage(root)
      set_modality_config(node, "media_attach", "anchor", "amy!", storage)
      set_modality(node, "speech_markup", False, storage)

      result = get_stats(session)
      self.assertEqual(
        result.effective_modalities_at_cursor["media_attach"], {"anchor": "amy!"}
      )
      self.assertEqual(
        result.effective_modalities_at_cursor["speech_markup"], {"enabled": False}
      )

  def test_chat_session_includes_required_modalities(self) -> None:
    from lens.core.modalities import Modality, register_modality
    from lens.core.operators.chat import ChatOperator

    class _ChatRequired(Modality):
      id = "stats_chat_required"
      builtin = False

    register_modality(_ChatRequired())
    ChatOperator.required_modalities = frozenset({"stats_chat_required"})

    try:
      with tempfile.TemporaryDirectory() as tmpdir:
        root = _init_repo(Path(tmpdir))
        session, node = _make_project(root)
        slug = "chat-sess"
        node.md_path().write_text(f"# test\n\n[chat:{slug}]: #\n")
        sess_dir = node.narrative_root / slug
        sess_dir.mkdir()
        (sess_dir / "_node.md").write_text(f"# {slug}\n")

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
        self.assertIn("stats_chat_required", result.modalities_at_cursor)
    finally:
      ChatOperator.required_modalities = frozenset()

