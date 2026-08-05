"""Gate matrix, refine-spec building, and ``apply`` for the ``media_attach`` modality."""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.attach import build_layered_embed
from lens.core.media import MediaService
from lens.core.modalities.catalog.media_attach import MediaAttachModality, apply_media_attach
from lens.core.modalities.types import ModalityContext
from lens.core.narrative import NarrativeNode
from lens.core.pinning import set_modality_config
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True, check=True
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


def _make_project(tmp: Path, *, with_mount: bool = True) -> tuple[Path, NarrativeNode]:
    toml = '[project]\nnarrative = "test"\n'
    if with_mount:
        toml += 'mount_point = "media"\n'
    (tmp / "lens.toml").write_text(toml, encoding="utf-8")
    if with_mount:
        (tmp / "media").mkdir()
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n", encoding="utf-8")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _ctx(root: Path, node: NarrativeNode) -> ModalityContext:
    return ModalityContext(
        session=None,
        narrative=node,
        focus_node=node,
        operator_name="write",
        crawl_result=None,
        params={},
        project_root=root,
    )


def _put(svc: MediaService, rel: str, extra: dict[str, object] | None = None) -> None:
    dir_part = "/".join(rel.split("/")[:-1])
    name = rel.split("/")[-1]
    svc.put_file(dir_part, name, io.BytesIO(b"hello"))
    if extra:
        svc.update_metadata(rel, extra)


class _RegistryCleanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        MediaService.clear_registry()

    def tearDown(self) -> None:
        MediaService.clear_registry()


# ---------------------------------------------------------------------------
# Gate matrix
# ---------------------------------------------------------------------------


class TestGates(_RegistryCleanTestCase):
    def test_no_mount_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)), with_mount=False)
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(gate.reason, "no mount_point configured in lens.toml")

    def test_no_anchor_in_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(gate.reason, "no modalities.media_attach.anchor in front matter")

    def test_capacity_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            (root / "lens.toml").write_text(
                '[project]\nnarrative = "test"\nmount_point = "media"\nmedia_search_index_limit = 1\n',
                encoding="utf-8",
            )
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "a.jpg", {"facets": {"emotion": "happy"}})
            _put(svc, "b.jpg", {"facets": {"emotion": "sad"}})
            set_modality_config(node, "media_attach", "anchor", "a!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(gate.reason, "media search index is over capacity")

    def test_anchor_matches_no_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy.jpg", {"facets": {"emotion": "happy"}})
            set_modality_config(node, "media_attach", "anchor", "nobody!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(gate.reason, "anchor matches no media")

    def test_all_matches_foreground_and_no_background_gates_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(
                svc,
                "amy_fg.jpg",
                {"facets": {"emotion": "happy"}, "composite": "foreground"},
            )
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(
                gate.reason,
                "every anchor match is a foreground composite and there is no background to build on",
            )

    def test_active_when_anchor_matches_a_plain_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy.jpg", {"facets": {"emotion": "happy"}})
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertTrue(gate.active)

    def test_matches_with_no_facets_at_all_are_excluded(self) -> None:
        """The hard-coded ``facets!`` term (see module docstring) means media
        with no ``facets`` metadata can never count as a match, even though
        the anchor alone would find it -- there's nothing to ever decide
        between, so it must not silently look "active"."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy.jpg")  # no facets metadata
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(gate.reason, "anchor matches no media")

    def test_multiple_matches_with_identical_facets_gates_off(self) -> None:
        """Two+ matches that are all properly faceted but agree on every
        value: the facets! requirement can't catch this (both are faceted),
        but there's still nothing to ever pick between."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy_1.jpg", {"facets": {"emotion": "happy"}})
            _put(svc, "amy_2.jpg", {"facets": {"emotion": "happy"}})
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertFalse(gate.active)
            self.assertEqual(
                gate.reason, "anchor matches 2 images but none differ on any facet"
            )

    def test_hand_typed_facets_term_in_anchor_is_harmless(self) -> None:
        """A user (or a future UI) typing `facets!` into the anchor themselves
        doesn't double-count or break matching -- required terms are AND'd."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy.jpg", {"facets": {"emotion": "happy"}})
            set_modality_config(node, "media_attach", "anchor", "facets! amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            gate = mod.gates(ctx)
            self.assertTrue(gate.active)


# ---------------------------------------------------------------------------
# workflow_refine_pass: built vs declined
# ---------------------------------------------------------------------------


class TestRefineSpec(_RegistryCleanTestCase):
    def test_declines_when_no_undecided_facets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            # Single-valued facet only -> already pinned, nothing to decide.
            _put(svc, "amy.jpg", {"facets": {"emotion": "happy"}})
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            spec = mod.workflow_refine_pass(ctx, "some prose")
            self.assertIsNone(spec)

    def test_builds_spec_when_facet_is_undecided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy_happy.jpg", {"facets": {"emotion": "happy"}})
            _put(svc, "amy_sad.jpg", {"facets": {"emotion": "sad"}})
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            spec = mod.workflow_refine_pass(ctx, "Amy smiled.")
            self.assertIsNotNone(spec)
            assert spec is not None
            self.assertIn("emotion", spec.instruction)
            self.assertIn("Amy smiled.", spec.instruction)
            self.assertIsNotNone(spec.apply)

    def test_declines_without_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)), with_mount=False)
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            spec = mod.workflow_refine_pass(ctx, "some prose")
            self.assertIsNone(spec)

    def test_declines_when_matches_have_no_facets_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy.jpg")  # no facets metadata
            set_modality_config(node, "media_attach", "anchor", "amy!", Storage(root))
            mod = MediaAttachModality()
            ctx = mod.prepare_context(_ctx(root, node))
            spec = mod.workflow_refine_pass(ctx, "some prose")
            self.assertIsNone(spec)


# ---------------------------------------------------------------------------
# apply()
# ---------------------------------------------------------------------------


class TestApplyMediaAttach(_RegistryCleanTestCase):
    def _service_with_two_emotions(self, root: Path) -> MediaService:
        svc = MediaService.for_project(root)
        assert svc is not None
        _put(svc, "amy_happy.jpg", {"facets": {"emotion": "happy"}})
        _put(svc, "amy_sad.jpg", {"facets": {"emotion": "sad"}})
        return svc

    def test_plain_image_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = self._service_with_two_emotions(root)
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '{"facets": {"emotion": "happy"}}',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg=None,
                text="Amy smiled.",
            )
            self.assertTrue(result.applied)
            self.assertIn("[facets: emotion=happy]: #", result.text)
            self.assertIn("amy_happy.jpg", result.text)
            self.assertTrue(result.text.endswith("Amy smiled."))

    def test_same_pick_as_previous_is_a_silent_no_op(self) -> None:
        """Re-picking the same facets as last time must not re-emit a duplicate attach."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = self._service_with_two_emotions(root)
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '{"facets": {"emotion": "happy"}}',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={"emotion": "happy"},
                previous_bg=None,
                text="Amy smiled.",
            )
            self.assertTrue(result.applied)
            self.assertEqual(result.text, "Amy smiled.")
            self.assertFalse(result.warnings)
            self.assertNotIn("[facets:", result.text)

    def test_foreground_over_previous_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "bg.jpg")
            _put(svc, "amy_happy.jpg", {"facets": {"emotion": "happy"}, "composite": "foreground"})
            _put(svc, "amy_sad.jpg", {"facets": {"emotion": "sad"}, "composite": "foreground"})
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '{"facets": {"emotion": "happy"}}',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg="bg.jpg",
                text="Amy smiled.",
            )
            self.assertTrue(result.applied)
            expected_embed = build_layered_embed("bg.jpg", "amy_happy.jpg")
            self.assertIn(expected_embed, result.text)

    def test_foreground_with_no_background_warns_and_keeps_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = MediaService.for_project(root)
            assert svc is not None
            _put(svc, "amy_happy.jpg", {"facets": {"emotion": "happy"}, "composite": "foreground"})
            _put(svc, "amy_sad.jpg", {"facets": {"emotion": "sad"}, "composite": "foreground"})
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '{"facets": {"emotion": "happy"}}',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg=None,
                text="Amy smiled.",
            )
            self.assertFalse(result.applied)
            self.assertEqual(result.text, "Amy smiled.")
            self.assertTrue(result.warnings)

    def test_unparseable_json_warns_and_keeps_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = self._service_with_two_emotions(root)
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                "not json at all",
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg=None,
                text="Amy smiled.",
            )
            self.assertFalse(result.applied)
            self.assertEqual(result.text, "Amy smiled.")
            self.assertTrue(result.warnings)

    def test_out_of_vocabulary_values_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = self._service_with_two_emotions(root)
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '{"facets": {"emotion": "furious"}}',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg=None,
                text="Amy smiled.",
            )
            self.assertFalse(result.applied)
            self.assertEqual(result.text, "Amy smiled.")
            self.assertTrue(result.warnings)

    def test_markdown_fenced_json_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            svc = self._service_with_two_emotions(root)
            undecided = {"emotion": frozenset({"happy", "sad"})}
            result = apply_media_attach(
                '```json\n{"facets": {"emotion": "sad"}}\n```',
                service=svc,
                anchor="amy!",
                undecided=undecided,
                previous_facets={},
                previous_bg=None,
                text="Amy frowned.",
            )
            self.assertTrue(result.applied)
            self.assertIn("amy_sad.jpg", result.text)


if __name__ == "__main__":
    unittest.main()
