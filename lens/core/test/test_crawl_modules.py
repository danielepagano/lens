"""Focused tests for crawl graph primitives and transforms."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import CrawlResult, apply_transforms_to_result
from lens.core.crawl_graph import (
    ComponentSource,
    CrawlComponent,
    CrawlGraph,
    RenderEffect,
    string_metadata,
)
from lens.core.crawl_transforms import (
    AtExpansionTransform,
    ParticipantTransform,
    RulesCompanionTransform,
    SecretDecodeTransform,
    StripStandaloneMountEmbedsTransform,
    expansion_policy_from_tags,
)
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> Path:
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
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _make_project(tmp: Path) -> Path:
    (tmp / "lens.toml").write_text('[project]\nnarrative = "test"\n')
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True)
    KnowledgeStore.clear_registry()
    MediaService.clear_registry()
    return tmp


def _add_kb(root: Path, canonical_id: str, text: str) -> None:
    type_name, key = canonical_id.split(".", 1)
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"kb {canonical_id}"], cwd=root, capture_output=True, check=True)
    KnowledgeStore.clear_registry()
    MediaService.clear_registry()


class TestCrawlGraphPrimitives(unittest.TestCase):
    def test_component_defaults_are_independent(self) -> None:
        first = CrawlComponent(id="a", kind="task")
        second = CrawlComponent(id="b", kind="task")

        first.metadata["x"] = "1"
        first.visibility.add("log")
        first.transform_history.append("changed")

        self.assertEqual(second.metadata, {})
        self.assertEqual(second.visibility, {"llm"})
        self.assertEqual(second.transform_history, [])

    def test_graph_helpers_and_clone(self) -> None:
        graph = CrawlGraph()
        graph.add_component(CrawlComponent(id="task-1", kind="task", text="A"))
        graph.add_component(CrawlComponent(id="task-2", kind="task", text="B"))
        graph.add_effect(
            RenderEffect(
                kind="test",
                token="@x",
                result="y",
                source_component_id="task-1",
            )
        )

        self.assertEqual(graph.next_id("task"), "task-3")
        self.assertEqual(len(graph.components_of_kind("task")), 2)
        self.assertIsNotNone(graph.component_by_id("task-1"))
        cloned = graph.components[0].clone_with(text="C", transform="copy")
        self.assertEqual(cloned.text, "C")
        self.assertEqual(cloned.transform_history, ["copy"])
        self.assertEqual(graph.effects[0].kind, "test")

    def test_string_metadata_normalizes_values(self) -> None:
        self.assertEqual(string_metadata({"a": 1, "b": True}), {"a": "1", "b": "True"})


class TestCrawlTransforms(unittest.TestCase):
    def test_secret_decode_transform_updates_text_and_history(self) -> None:
        graph = CrawlGraph()
        graph.add_component(
            CrawlComponent(
                id="current",
                kind="current_narrative",
                text="Visible <!-- ai:secret:\ngur frperg\n-->",
            )
        )

        SecretDecodeTransform().apply(graph)

        self.assertIn("the secret", graph.components[0].text)
        self.assertIn("secret-decode", graph.components[0].transform_history)

    def test_secret_decode_transform_is_idempotent(self) -> None:
        # ROT13 is an involution, and the normal flow runs the default
        # transforms twice: once in crawl(), again in _prepare_render_graph over
        # the render-time components it adds. Without a guard the second pass
        # re-encodes, the model is shown ciphertext, and copying it back leaks
        # plaintext on persist (issue #74).
        graph = CrawlGraph()
        graph.add_component(
            CrawlComponent(
                id="kb:front.blight",
                kind="knowledge",
                text="Visible <!-- ai:secret:\ngur frperg\n-->",
            )
        )

        for _ in range(3):
            SecretDecodeTransform().apply(graph)

        self.assertIn("the secret", graph.components[0].text)
        self.assertNotIn("gur frperg", graph.components[0].text)
        self.assertEqual(
            graph.components[0].transform_history.count("secret-decode"), 1
        )

    def test_secret_decode_transform_still_reaches_later_components(self) -> None:
        """A second pass must skip decoded components without skipping new ones."""
        graph = CrawlGraph()
        graph.add_component(
            CrawlComponent(
                id="kb:front.blight",
                kind="knowledge",
                text="Visible <!-- ai:secret:\ngur frperg\n-->",
            )
        )
        SecretDecodeTransform().apply(graph)
        graph.add_component(
            CrawlComponent(
                id="render-task",
                kind="task",
                text="Task <!-- ai:secret:\nnabgure bar\n-->",
            )
        )

        SecretDecodeTransform().apply(graph)

        self.assertIn("the secret", graph.components[0].text)
        self.assertIn("another one", graph.components[1].text)

    def test_strip_mount_embeds_removes_standalone_attachment_lines(self) -> None:
        graph = CrawlGraph()
        graph.add_component(
            CrawlComponent(
                id="cur",
                kind="current_narrative",
                text="Hello\n![x](/mount/file/a.png)\n",
            )
        )
        StripStandaloneMountEmbedsTransform().apply(graph)
        self.assertEqual(graph.components[0].text, "Hello\n")
        self.assertIn("strip-mount-embeds", graph.components[0].transform_history)

    def test_inline_kb_expansion_recurses_into_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "visual.palette", "@var:color glow")
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("visual.palette", ["inline"]))
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()

            graph = CrawlGraph(project_root=root, vars={"color": "blue"})
            graph.add_component(
                CrawlComponent(
                    id="task",
                    kind="task",
                    text="Paint @visual.palette.",
                    source=ComponentSource(kind="operator", identifier="test"),
                )
            )

            AtExpansionTransform(project_root=root, storage=Storage(root)).apply(graph)

            self.assertEqual(graph.components[0].text, "Paint blue glow.")
            self.assertTrue(any(effect.kind == "kb-inline" for effect in graph.effects))
            self.assertTrue(any(effect.kind == "var" for effect in graph.effects))

    def test_reference_mentions_are_deduped_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person.amy", "Amy details")

            graph = CrawlGraph(project_root=root)
            graph.add_component(
                CrawlComponent(
                    id="prompt",
                    kind="metadata",
                    text="@person.amy and @person.amy",
                    visibility={"hidden"},
                )
            )

            AtExpansionTransform(project_root=root, storage=Storage(root)).apply(graph)

            refs = [c for c in graph.components if c.id == "mention-kb:person.amy"]
            self.assertEqual(len(refs), 1)
            self.assertIn("person.amy", graph.pinned_ids)

    def test_force_inline_kb_inlines_reference_policy_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person.amy", "Amy details")

            graph = CrawlGraph(project_root=root)
            graph.add_component(
                CrawlComponent(
                    id="prompt",
                    kind="task",
                    text="@person.amy sitting.",
                    role="user",
                    source=ComponentSource(kind="prompt", identifier="test"),
                    visibility={"llm"},
                )
            )

            AtExpansionTransform(
                project_root=root,
                storage=Storage(root),
                force_inline_kb=True,
            ).apply(graph)

            self.assertEqual(graph.components[0].text, "Amy details sitting.")
            self.assertEqual(
                len([c for c in graph.components if c.id.startswith("mention-kb:")]),
                0,
            )

    def test_participant_transform_adds_log_components(self) -> None:
        graph = CrawlGraph()

        ParticipantTransform(participants={"as": "npc.bob", "with": "pc.amy"}).apply(graph)

        self.assertEqual(graph.metadata["participant:as"], "npc.bob")
        self.assertEqual(graph.metadata["participant:with"], "pc.amy")
        self.assertEqual(len(graph.components_of_kind("participant")), 2)
        self.assertEqual(graph.components_of_kind("participant")[0].visibility, {"log"})

    def test_inline_kb_cycle_emits_log_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "lore.alpha", "alpha refers to @lore.beta")
            _add_kb(root, "lore.beta", "beta refers to @lore.alpha")
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("lore.alpha", ["inline"]))
            self.assertIsNone(kb.add_tags("lore.beta", ["inline"]))
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()

            graph = CrawlGraph(project_root=root)
            graph.add_component(
                CrawlComponent(
                    id="task",
                    kind="task",
                    text="See @lore.alpha.",
                )
            )

            AtExpansionTransform(
                project_root=root, storage=Storage(root), max_depth=4
            ).apply(graph)

            warnings = [c for c in graph.components if c.kind == "warning"]
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0].visibility, {"log"})

    def test_expansion_policy_from_tags_edge_cases(self) -> None:
        self.assertEqual(expansion_policy_from_tags([]).mode, "reference")
        self.assertEqual(expansion_policy_from_tags(["important"]).mode, "reference")
        self.assertEqual(expansion_policy_from_tags(["inline"]).mode, "inline")
        self.assertEqual(
            expansion_policy_from_tags(["important", "inline", "other"]).mode,
            "inline",
        )

    def test_apply_transforms_to_result_resyncs_legacy_fields(self) -> None:
        class _AddKnowledge:
            name = "test-add"

            def apply(self, graph: CrawlGraph) -> CrawlGraph:
                graph.add_component(
                    CrawlComponent(
                        id="kb:custom.x",
                        kind="knowledge",
                        text="custom block",
                    )
                )
                if "custom.x" not in graph.pinned_ids:
                    graph.pinned_ids.append("custom.x")
                return graph

        graph = CrawlGraph()
        result = CrawlResult(graph)

        apply_transforms_to_result(result, [_AddKnowledge()])

        self.assertIn("custom block", result.knowledge)
        self.assertIn("custom.x", result.pinned_ids)

    def test_rules_companion_transform_adds_existing_rules_for_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "rules.encounter", "Encounter rules")

            graph = CrawlGraph(
                project_root=root,
                pinned_ids=["rules.system", "pc.alice", "encounter.bridge"],
            )

            RulesCompanionTransform(project_root=root, storage=Storage(root)).apply(graph)

            self.assertIn("rules.encounter", graph.pinned_ids)
            self.assertTrue(
                any(
                    component.id == "rules-companion:rules.encounter"
                    for component in graph.components
                )
            )
            self.assertTrue(any(effect.kind == "rules-companion" for effect in graph.effects))


if __name__ == "__main__":
    unittest.main()
