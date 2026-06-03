"""Tests for TTS mount cache sync (prune, rename, delete, collate hooks)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.narrative import NarrativeNode
from lens.core.pinning import TTS_CACHED
from lens.core.speech.chunks import chunk_id, chunks_for_node_text, tts_cache_mount_prefix
from lens.core.speech.tts_cache_sync import (
    migrate_collate_verbatim_audio,
    narrative_destination_path_to_node,
    narrative_storage_path_to_node,
    node_uses_tts_cache,
    prune_tts_orphans,
    remove_tts_cache_subtree,
    text_has_tts_cached,
)
from lens.core.storage import Storage


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.co"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    (root / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _fm(rev: int = 1) -> str:
    return f"""[
    {TTS_CACHED}: {rev}
]: #

"""


class TestTextHasTtsCached(unittest.TestCase):
    def test_false_without_flag(self) -> None:
        self.assertFalse(text_has_tts_cached("Hello.\n"))

    def test_true_with_flag(self) -> None:
        self.assertTrue(text_has_tts_cached(_fm() + "Hello.\n"))


class TestNarrativePathToNode(unittest.TestCase):
    def test_leaf_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "narrative" / "camp").mkdir(parents=True)
            p = root / "narrative" / "camp" / "scene.md"
            p.write_text("x", encoding="utf-8")
            n = narrative_storage_path_to_node(root, p)
            assert n is not None
            self.assertEqual(n.key_path, ("scene",))
            dst = root / "narrative" / "camp" / "newscene.md"
            n2 = narrative_destination_path_to_node(root, dst)
            assert n2 is not None
            self.assertEqual(n2.key_path, ("newscene",))


class TestPruneAndDelete(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self.mount = self.root / "media"
        self.mount.mkdir()
        (self.root / "lens.toml").write_text(
            f'[project]\nnarrative = "camp"\nmount_point = "{self.mount}"\n',
            encoding="utf-8",
        )
        nar = self.root / "narrative" / "camp"
        nar.mkdir(parents=True)
        self.node_path = nar / "scene.md"
        self.node = NarrativeNode(narrative_root=nar, key_path=("scene",))

    def test_no_mount_work_without_tts_flag(self) -> None:
        self.node_path.write_text("Line one.\nLine two.\n", encoding="utf-8")
        prefix = tts_cache_mount_prefix(self.node)
        (self.mount / prefix).mkdir(parents=True)
        orphan = self.mount / prefix / "orphan.mp3"
        orphan.write_bytes(b"x")
        prune_tts_orphans(self.root, self.node)
        self.assertTrue(orphan.exists())

    def test_prune_removes_orphan_mp3(self) -> None:
        body = "Only line.\n"
        cid = chunk_id(1, body.strip())
        self.node_path.write_text(_fm() + body, encoding="utf-8")
        prefix = tts_cache_mount_prefix(self.node)
        (self.mount / prefix).mkdir(parents=True)
        good = self.mount / prefix / f"{cid}.mp3"
        bad = self.mount / prefix / "stale-id.mp3"
        good.write_bytes(b"a")
        bad.write_bytes(b"b")
        prune_tts_orphans(self.root, self.node)
        self.assertTrue(good.exists())
        self.assertFalse(bad.exists())

    def test_delete_removes_tree_when_flag_set(self) -> None:
        self.node_path.write_text(_fm() + "Hi.\n", encoding="utf-8")
        prefix = tts_cache_mount_prefix(self.node)
        (self.mount / prefix / "nested").mkdir(parents=True)
        f = self.mount / prefix / "nested" / "x.mp3"
        f.write_bytes(b"x")
        raw = self.node_path.read_text(encoding="utf-8")
        remove_tts_cache_subtree(self.root, self.node, raw_md=raw)
        self.assertFalse((self.mount / prefix).exists())


class TestStorageHooks(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_git_repo(self.root)
        self.mount = self.root / "media"
        self.mount.mkdir()
        (self.root / "lens.toml").write_text(
            f'[project]\nnarrative = "camp"\nmount_point = "{self.mount}"\n',
            encoding="utf-8",
        )
        self.nar = self.root / "narrative" / "camp"
        self.nar.mkdir(parents=True)
        self.scene = self.nar / "scene.md"

    def test_write_file_prune_only_with_flag(self) -> None:
        body = "Hello world.\n"
        self.scene.write_text(_fm() + body, encoding="utf-8")
        node = NarrativeNode(narrative_root=self.nar, key_path=("scene",))
        prefix = tts_cache_mount_prefix(node)
        (self.mount / prefix).mkdir(parents=True)
        stale = self.mount / prefix / "gone.mp3"
        stale.write_bytes(b"x")
        st = Storage(self.root, owner=None)
        st.write_file(self.scene, _fm() + body)
        self.assertFalse(stale.exists())

    def test_rename_moves_cache_prefix(self) -> None:
        body = "Renameme.\n"
        self.scene.write_text(_fm() + body, encoding="utf-8")
        old_n = NarrativeNode(narrative_root=self.nar, key_path=("scene",))
        prefix_old = tts_cache_mount_prefix(old_n)
        (self.mount / prefix_old).mkdir(parents=True)
        cid = chunk_id(1, body.strip())
        (self.mount / prefix_old / f"{cid}.mp3").write_bytes(b"a")
        new_path = self.nar / "renamed.md"
        st = Storage(self.root, owner=None)
        st.rename(self.scene, new_path)
        new_n = NarrativeNode(narrative_root=self.nar, key_path=("renamed",))
        prefix_new = tts_cache_mount_prefix(new_n)
        self.assertTrue((self.mount / prefix_new / f"{cid}.mp3").exists())
        self.assertFalse((self.mount / prefix_old).exists())

    def test_rename_skips_without_flag(self) -> None:
        self.scene.write_text("No flag.\n", encoding="utf-8")
        old_n = NarrativeNode(narrative_root=self.nar, key_path=("scene",))
        prefix_old = tts_cache_mount_prefix(old_n)
        (self.mount / prefix_old).mkdir(parents=True)
        (self.mount / prefix_old / "x.mp3").write_bytes(b"x")
        new_path = self.nar / "renamed.md"
        st = Storage(self.root, owner=None)
        st.rename(self.scene, new_path)
        self.assertTrue((self.mount / prefix_old / "x.mp3").exists())

    def test_delete_removes_cache_with_flag(self) -> None:
        self.scene.write_text(_fm() + "Bye.\n", encoding="utf-8")
        node = NarrativeNode(narrative_root=self.nar, key_path=("scene",))
        prefix = tts_cache_mount_prefix(node)
        (self.mount / prefix).mkdir(parents=True)
        (self.mount / prefix / "a.mp3").write_bytes(b"a")
        st = Storage(self.root, owner=None)
        st.delete_file(self.scene)
        self.assertFalse(self.scene.exists())
        self.assertFalse((self.mount / prefix).exists())


class TestCollateMigration(unittest.TestCase):
    def test_migrate_moves_verbatim_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mount = root / "media"
            mount.mkdir()
            (root / "lens.toml").write_text(
                f'[project]\nnarrative = "camp"\nmount_point = "{mount}"\n',
                encoding="utf-8",
            )
            nar = root / "narrative" / "camp"
            nar.mkdir(parents=True)
            parent = NarrativeNode(narrative_root=nar, key_path=())
            parent_path = nar / "_node.md"
            body = "Verbatim line for collate.\n"
            parent_path.write_text(_fm() + body, encoding="utf-8")
            child = parent.child_node("sec")
            pfx_p = tts_cache_mount_prefix(parent)
            (mount / pfx_p).mkdir(parents=True)
            cid = next(c.id for c in chunks_for_node_text(body))
            (mount / pfx_p / f"{cid}.mp3").write_bytes(b"p")
            migrate_collate_verbatim_audio(
                root,
                parent_node=parent,
                child_node=child,
                selected_text=body.strip(),
                parent_had_tts=True,
            )
            pfx_c = tts_cache_mount_prefix(child)
            self.assertTrue((mount / pfx_c / f"{cid}.mp3").exists())


class TestNodeUsesTtsCache(unittest.TestCase):
    def test_reads_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nar = Path(tmp) / "narrative" / "c"
            nar.mkdir(parents=True)
            p = nar / "n.md"
            p.write_text(_fm() + "x\n", encoding="utf-8")
            n = NarrativeNode(narrative_root=nar, key_path=("n",))
            self.assertTrue(node_uses_tts_cache(n))


class TestLeafFolderConversionPreservesTtsCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_git_repo(self.root)
        self.mount = self.root / "media"
        self.mount.mkdir()
        (self.root / "lens.toml").write_text(
            f'[project]\nnarrative = "camp"\nmount_point = "{self.mount}"\n',
            encoding="utf-8",
        )
        self.nar = self.root / "narrative" / "camp"
        self.nar.mkdir(parents=True)
        (self.nar / "_node.md").write_text("# root\n", encoding="utf-8")

    def test_to_folder_keeps_cache_mp3(self) -> None:
        body = "Chapter body line.\n"
        leaf = self.nar / "ch1.md"
        leaf.write_text(_fm() + body, encoding="utf-8")
        node = NarrativeNode(narrative_root=self.nar, key_path=("ch1",))
        prefix = tts_cache_mount_prefix(node)
        (self.mount / prefix).mkdir(parents=True)
        cid = chunk_id(1, body.strip())
        mp3 = self.mount / prefix / f"{cid}.mp3"
        mp3.write_bytes(b"audio")
        st = Storage(self.root, owner=None)
        node.to_folder(st)
        self.assertTrue(mp3.exists())

    def test_to_leaf_keeps_cache_mp3(self) -> None:
        body = "Folder chapter line.\n"
        folder = self.nar / "ch1"
        folder.mkdir()
        (folder / "_node.md").write_text(_fm() + body, encoding="utf-8")
        node = NarrativeNode(narrative_root=self.nar, key_path=("ch1",))
        prefix = tts_cache_mount_prefix(node)
        (self.mount / prefix).mkdir(parents=True)
        cid = chunk_id(1, body.strip())
        mp3 = self.mount / prefix / f"{cid}.mp3"
        mp3.write_bytes(b"audio")
        st = Storage(self.root, owner=None)
        node.to_leaf(st)
        self.assertTrue(mp3.exists())

