"""Modality registry, resolution, and inline operator integration."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock, patch

from lens.core.context import CrawlResult, CrawlSpec, crawl
from lens.core.llm_run import LlmRunRequest
from lens.core.crawl_graph import CrawlComponent, CrawlGraph
from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.modalities import (
    Modality,
    ModalityContext,
    RefinePassSpec,
    apply_modality_crawl,
    apply_modality_post_refine_to_artifacts,
    clear_registry_for_tests,
    get_modality,
    merge_modality_command_tools,
    merge_modality_crawl_spec,
    refine_step_id,
    register_modality,
    resolve_modalities,
)
from lens.core.generation_artifacts import compose_for_operator
from lens.core.modalities.types import (
    CommandToolsContribution,
    CrawlContribution,
    ModalityGateResult,
    ResolvedModalities,
)
from lens.core.operators.write import WriteOperator
from lens.core.pinning import collect_modalities_fm, set_modality
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.workflow_runner import WorkflowRunner
from lens.core.narrative import NarrativeNode
from lens.core.test.llm_run_mock import mock_run_llm

SPY_MODALITY_ID = "test_spy"
SPY_DEP_ID = "test_spy_dep"
DEFAULT_A_ID = "default_a"
DEFAULT_B_ID = "default_b"
GATED_ID = "gated_test"
CRAWL_MARKER_ID = "crawl_marker"
PIN_MODALITY_ID = "pin_modality"
TOOLS_MODALITY_ID = "tools_modality"
REFINE_MODALITY_ID = "refine_modality"
MODALITY_PIN_KB_ID = "person.modalitypin"


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
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp


def _add_kb(root: Path, type_name: str, key: str, content: str) -> None:
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


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


@dataclass
class _HookCounts:
    gates: int = 0
    crawl_contributions: int = 0
    prompt_addenda: int = 0
    command_tools: int = 0
    workflow_post_process: int = 0
    workflow_refine_pass: int = 0


class SpyModality(Modality):
    """Test double that records which hooks ran."""

    id = SPY_MODALITY_ID

    def __init__(self) -> None:
        self.counts = _HookCounts()

    @property
    def contributes_workflow_post(self) -> bool:
        return True

    def dependencies(self) -> frozenset[str]:
        return frozenset({SPY_DEP_ID})

    def gates(self, ctx: ModalityContext) -> ModalityGateResult:
        del ctx
        self.counts.gates += 1
        return ModalityGateResult()

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        del ctx
        self.counts.crawl_contributions += 1
        return CrawlContribution()

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        del ctx
        self.counts.prompt_addenda += 1
        return ("<!-- spy-prompt -->",)

    def command_tools(self, ctx: ModalityContext) -> CommandToolsContribution | None:
        del ctx
        self.counts.command_tools += 1
        return None

    def workflow_post_process(self, ctx: ModalityContext, text: str) -> str:
        del ctx
        self.counts.workflow_post_process += 1
        return text + "\n<!-- spy-post -->\n"

    def workflow_refine_pass(self, ctx: ModalityContext, text: str) -> RefinePassSpec | None:
        del ctx, text
        self.counts.workflow_refine_pass += 1
        return RefinePassSpec(instruction="spy refine instruction")


class _SpyDepModality(Modality):
    id = SPY_DEP_ID


class _DefaultAModality(Modality):
    id = DEFAULT_A_ID
    builtin = True


class _DefaultBModality(Modality):
    id = DEFAULT_B_ID
    builtin = True


class _GatedModality(Modality):
    id = GATED_ID

    def gates(self, ctx: ModalityContext) -> ModalityGateResult:
        del ctx
        return ModalityGateResult(active=False, reason="test gate")


class _AddMarkerTransform:
    name = "test-modality-marker"

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        graph.add_component(
            CrawlComponent(
                id="modality-crawl-marker",
                kind="extra",
                text="MODALITY_CRAWL_MARKER",
            )
        )
        return graph


class _CrawlMarkerModality(Modality):
    id = CRAWL_MARKER_ID

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        del ctx
        return CrawlContribution(
            transforms=(_AddMarkerTransform(),),
            extra_pins=(MODALITY_PIN_KB_ID,),
        )


class _PinKbModality(Modality):
    id = PIN_MODALITY_ID

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        del ctx
        return CrawlContribution(extra_pins=(MODALITY_PIN_KB_ID,))


class _WriteRequiresPin(WriteOperator):
    required_modalities: ClassVar[frozenset[str]] = frozenset({PIN_MODALITY_ID})


async def _modality_tool_handler(_args: dict[str, object], _root: Path) -> str:
    del _args, _root
    return "ok"


class _CommandToolsModality(Modality):
    id = TOOLS_MODALITY_ID

    def command_tools(self, ctx: ModalityContext) -> CommandToolsContribution | None:
        del ctx
        return CommandToolsContribution(
            tools=[{"type": "function", "function": {"name": "modality_tool"}}],
            handlers={"modality_tool": _modality_tool_handler},
        )


class _RefineModality(Modality):
    id = REFINE_MODALITY_ID

    def __init__(self) -> None:
        self.counts = _HookCounts()

    def workflow_refine_pass(self, ctx: ModalityContext, text: str) -> RefinePassSpec | None:
        del ctx, text
        self.counts.workflow_refine_pass += 1
        return RefinePassSpec(instruction="refine from test modality")


class _WriteRequiresSpy(WriteOperator):
    required_modalities: ClassVar[frozenset[str]] = frozenset({SPY_MODALITY_ID})


class _RegistryCleanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_for_tests()

    def tearDown(self) -> None:
        clear_registry_for_tests()


class _SpyIntegrationTestCase(_RegistryCleanTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._spy = SpyModality()
        register_modality(self._spy)
        register_modality(_SpyDepModality())

    def _spy_modality(self) -> SpyModality:
        mod = get_modality(SPY_MODALITY_ID)
        assert isinstance(mod, SpyModality)
        return mod


class TestModalityResolution(_RegistryCleanTestCase):
    def test_fm_opt_in_resolves_spy_and_dependency(self) -> None:
        register_modality(SpyModality())
        register_modality(_SpyDepModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, SPY_MODALITY_ID, True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertEqual(set(resolved.active_ids), {SPY_DEP_ID, SPY_MODALITY_ID})
            self.assertLess(
                resolved.active_ids.index(SPY_DEP_ID),
                resolved.active_ids.index(SPY_MODALITY_ID),
            )

    def test_operator_required_without_fm(self) -> None:
        register_modality(SpyModality())
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(_init_repo(Path(tmp)))
            resolved, _ = resolve_modalities(_WriteRequiresSpy, narrative)
            self.assertIn(SPY_MODALITY_ID, resolved.active_ids)

    def test_builtin_modalities_active_without_fm(self) -> None:
        register_modality(_DefaultAModality())
        register_modality(_DefaultBModality())
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(_init_repo(Path(tmp)))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn(DEFAULT_A_ID, resolved.active_ids)
            self.assertIn(DEFAULT_B_ID, resolved.active_ids)

    def test_fm_false_opt_out_of_builtin_stack(self) -> None:
        register_modality(_DefaultAModality())
        register_modality(_DefaultBModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, DEFAULT_B_ID, False, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn(DEFAULT_A_ID, resolved.active_ids)
            self.assertNotIn(DEFAULT_B_ID, resolved.active_ids)

    def test_unknown_fm_modality_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, "not_registered", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertNotIn("not_registered", resolved.active_ids)
            self.assertTrue(any("not_registered" in w for w in resolved.warnings))

    def test_gates_exclude_modality(self) -> None:
        register_modality(_GatedModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, GATED_ID, True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertNotIn(GATED_ID, resolved.active_ids)
            self.assertTrue(any(GATED_ID in w for w in resolved.warnings))

    def test_collect_modalities_fm_child_overrides_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            scene_dir = narrative.narrative_root / "scene"
            scene_dir.mkdir()
            (scene_dir / "_node.md").write_text("# scene\n")
            scene = NarrativeNode(narrative_root=narrative.narrative_root, key_path=("scene",))
            set_modality(narrative, "layered_flag", True, storage)
            set_modality(scene, "layered_flag", False, storage)
            merged = collect_modalities_fm(scene)
            self.assertFalse(merged["layered_flag"])


class TestModalityApply(_RegistryCleanTestCase):
    def test_merge_modality_command_tools(self) -> None:
        register_modality(_CommandToolsModality())
        resolved = ResolvedModalities(active_ids=(TOOLS_MODALITY_ID,))
        ctx = ModalityContext(
            session=None,
            narrative=NarrativeNode(narrative_root=Path("/x"), key_path=()),
            focus_node=NarrativeNode(narrative_root=Path("/x"), key_path=()),
            operator_name="write",
            crawl_result=None,
            params={},
            project_root=Path("/x"),
        )
        tools, handlers = merge_modality_command_tools(None, None, resolved, ctx)
        assert tools is not None
        assert handlers is not None
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "modality_tool")
        self.assertIn("modality_tool", handlers)

    def test_apply_modality_crawl_applies_transforms(self) -> None:
        register_modality(_CrawlMarkerModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, CRAWL_MARKER_ID, True, Storage(root))
            crawl_result, ctx, resolved = WriteOperator.crawl_with_modalities(
                CrawlSpec.of(narrative, storage=Storage(root)),
                {},
                session=None,
                narrative=narrative,
            )
            apply_modality_crawl(crawl_result, resolved, ctx)
            texts = [c.text for c in crawl_result.graph.components]
            self.assertIn("MODALITY_CRAWL_MARKER", texts)

    def test_merge_modality_crawl_spec_extra_pins_in_crawl(self) -> None:
        register_modality(_PinKbModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "modalitypin", "Pinned by modality")
            spec = CrawlSpec.of(narrative, storage=Storage(root))
            resolved, _ = resolve_modalities(
                WriteOperator,
                narrative,
                default_ids=frozenset({PIN_MODALITY_ID}),
            )
            ctx = ModalityContext(
                session=None,
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            merged = merge_modality_crawl_spec(spec, resolved, ctx)
            self.assertEqual(merged.extra_pins, (MODALITY_PIN_KB_ID,))
            crawl_result = crawl(merged)
            self.assertIn(MODALITY_PIN_KB_ID, crawl_result.pinned_ids)
            self.assertEqual(len(crawl_result.knowledge), 1)

    def test_crawl_with_modalities_merges_pins_and_transforms(self) -> None:
        register_modality(_CrawlMarkerModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "modalitypin", "Pinned by modality")
            set_modality(narrative, CRAWL_MARKER_ID, True, Storage(root))
            crawl_result, ctx, resolved = WriteOperator.crawl_with_modalities(
                CrawlSpec.of(narrative, storage=Storage(root)),
                {},
                session=None,
                narrative=narrative,
            )
            apply_modality_crawl(crawl_result, resolved, ctx)
            texts = [c.text for c in crawl_result.graph.components]
            self.assertIn("MODALITY_CRAWL_MARKER", texts)
            self.assertIn(MODALITY_PIN_KB_ID, crawl_result.pinned_ids)

    def test_extra_unpins_via_merge_modality_crawl_spec(self) -> None:
        class _UnpinModality(Modality):
            id = "unpin_modality"

            def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
                del ctx
                return CrawlContribution(extra_unpins=("place.blocked",))

        register_modality(_UnpinModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "blocked", "Blocked place")
            root_node = NarrativeNode(narrative_root=narrative.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - place.blocked\n]: #\n\n# test\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "fm pin"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            spec = CrawlSpec.of(narrative, storage=Storage(root))
            resolved, _ = resolve_modalities(
                WriteOperator,
                narrative,
                default_ids=frozenset({"unpin_modality"}),
            )
            ctx = ModalityContext(
                session=None,
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            without = crawl(spec)
            self.assertEqual(len(without.knowledge), 1)
            merged = merge_modality_crawl_spec(spec, resolved, ctx)
            with_unpin = crawl(merged)
            self.assertEqual(with_unpin.knowledge, [])


class _PostOnlyModality(Modality):
    id = "post_only_test"

    @property
    def contributes_workflow_post(self) -> bool:
        return True

    def workflow_post_process(self, ctx: ModalityContext, text: str) -> str:
        del ctx
        return text + "\n<!-- post-only -->\n"


class TestRefineSpecCache(_RegistryCleanTestCase):
    def test_cache_refine_ids_only_once(self) -> None:
        from lens.core.modalities.workflow import cache_refine_modality_ids_on_pending
        from lens.core.modalities.types import PendingInlinePersist
        register_modality(_RefineModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, REFINE_MODALITY_ID, True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            ctx = ModalityContext(
                session=ProjectSession(root, root),
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            pending = PendingInlinePersist(
                mode="start",
                cursor=narrative,
                tag="",
                artifacts=GenerationArtifacts(
                    segments=[GenerationSegment("prose", "line\n")]
                ),
                verbatim_prefix="",
                existing_ann=None,
                owner=narrative.to_address(),
                narrative=narrative,
                operator_name="write",
            )
            mod = get_modality(REFINE_MODALITY_ID)
            assert isinstance(mod, _RefineModality)
            mod.counts.workflow_refine_pass = 0
            cache_refine_modality_ids_on_pending(pending, resolved, ctx)
            cache_refine_modality_ids_on_pending(pending, resolved, ctx)
            self.assertEqual(mod.counts.workflow_refine_pass, 1)
            self.assertEqual(pending.refine_modality_ids, (REFINE_MODALITY_ID,))


class TestModalityPostRefineApply(unittest.IsolatedAsyncioTestCase, _RegistryCleanTestCase):
    async def test_apply_modality_post_refine_runs_post_hook(self) -> None:
        register_modality(_PostOnlyModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, "post_only_test", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            ctx = ModalityContext(
                session=ProjectSession(root, root),
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=None,
                params={},
                project_root=root,
            )
            artifacts = GenerationArtifacts(
                segments=[GenerationSegment("prose", "Draft.\n")]
            )
            out, _warnings = await apply_modality_post_refine_to_artifacts(
                ProjectSession(root, root),
                artifacts,
                "write",
                resolved,
                ctx,
            )
            text = compose_for_operator(out, "write")
            self.assertIn("post-only", text)


class TestModalityInlineIntegration(_SpyIntegrationTestCase):
    async def _run_write(
        self,
        root: Path,
        narrative: Any,
        *,
        operator: type[WriteOperator] = WriteOperator,
        workflow: WorkflowRunner | None = None,
    ) -> None:
        async def _text(*_a: object, **_k: object) -> str:
            return "Generated body.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            with contextlib.redirect_stdout(io.StringIO()):
                with contextlib.redirect_stderr(io.StringIO()):
                    await operator.run_inline(
                        session=ProjectSession(root, root),
                        narrative=narrative,
                        prompt="go",
                        pins=[],
                        unpins=[],
                        llm_id="mock",
                        retry=False,
                        workflow=workflow,
                    )

    def test_write_without_activation_does_not_call_spy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            asyncio.run(self._run_write(root, narrative))
            spy = self._spy_modality()
            self.assertEqual(spy.counts.prompt_addenda, 0)
            self.assertEqual(spy.counts.workflow_post_process, 0)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertNotIn("spy-prompt", text)
            self.assertNotIn("spy-post", text)

    def test_write_fm_opt_in_calls_prompt_and_post_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, SPY_MODALITY_ID, True, Storage(root))
            asyncio.run(self._run_write(root, narrative))
            spy = self._spy_modality()
            self.assertGreaterEqual(spy.counts.prompt_addenda, 1)
            self.assertGreaterEqual(spy.counts.crawl_contributions, 1)
            self.assertGreaterEqual(spy.counts.workflow_post_process, 1)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn("spy-post", text)
            self.assertIn("Generated body.", text)

    def test_write_required_modalities_calls_spy_without_fm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            asyncio.run(self._run_write(root, narrative, operator=_WriteRequiresSpy))
            spy = self._spy_modality()
            self.assertGreaterEqual(spy.counts.prompt_addenda, 1)
            self.assertGreaterEqual(spy.counts.workflow_post_process, 1)

    def test_write_pin_modality_includes_kb_in_crawl(self) -> None:
        register_modality(_PinKbModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "modalitypin", "From pin modality")
            captured: list[CrawlResult] = []

            async def _capture_crawl(request: LlmRunRequest, **_k: object) -> GenerationArtifacts:
                if request.crawl_result is not None:
                    captured.append(request.crawl_result)
                return GenerationArtifacts(
                    segments=[GenerationSegment("prose", "Generated body.\n")]
                )

            with patch("lens.core.operator.run_llm", _capture_crawl):
                with contextlib.redirect_stdout(io.StringIO()):
                    with contextlib.redirect_stderr(io.StringIO()):
                        asyncio.run(
                            _WriteRequiresPin.run_inline(
                                session=ProjectSession(root, root),
                                narrative=narrative,
                                prompt="go",
                                pins=[],
                                unpins=[],
                                llm_id="mock",
                                retry=False,
                            )
                        )
            self.assertTrue(captured)
            self.assertIn(MODALITY_PIN_KB_ID, captured[-1].pinned_ids)

    def test_skip_workflow_post_avoids_post_hook_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, SPY_MODALITY_ID, True, Storage(root))
            skip_sent = False

            async def on_event(payload: dict[str, object]) -> None:
                nonlocal skip_sent
                if (
                    not skip_sent
                    and payload.get("type") == "workflow"
                    and payload.get("action") == "plan"
                ):
                    steps = payload.get("steps")
                    if isinstance(steps, list):
                        step_dicts = [
                            cast(dict[str, object], s)
                            for s in cast(list[object], steps)
                            if isinstance(s, dict)
                        ]
                    else:
                        step_dicts = []
                    if any(s.get("id") == "workflow_post" for s in step_dicts):
                        runner.signal_action("workflow_post", "skip")
                        skip_sent = True

            runner = WorkflowRunner(on_event=on_event)
            asyncio.run(self._run_write(root, narrative, workflow=runner))
            spy = self._spy_modality()
            self.assertGreaterEqual(spy.counts.prompt_addenda, 1)
            self.assertEqual(spy.counts.workflow_post_process, 0)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertNotIn("spy-post", text)

    def test_workflow_refine_calls_spy_and_persists_refined_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, SPY_MODALITY_ID, True, Storage(root))

            refined = GenerationArtifacts(
                segments=[GenerationSegment("prose", "Spy refined.\n")]
            )

            async def _fake_refine(*_a: object, **_k: object) -> GenerationArtifacts:
                return refined

            async def _draft(*_a: object, **_k: object) -> str:
                return "Draft.\n"

            async def _run() -> None:
                with patch("lens.core.operator.run_llm", mock_run_llm(_draft)):
                    with patch(
                        "lens.core.modalities.workflow.run_refine_pass",
                        new=AsyncMock(side_effect=_fake_refine),
                    ):
                        with contextlib.redirect_stdout(io.StringIO()):
                            with contextlib.redirect_stderr(io.StringIO()):
                                await WriteOperator.run_inline(
                                    session=ProjectSession(root, root),
                                    narrative=narrative,
                                    prompt="go",
                                    pins=[],
                                    unpins=[],
                                    llm_id="mock",
                                    retry=False,
                                )

            asyncio.run(_run())
            spy = self._spy_modality()
            self.assertGreaterEqual(spy.counts.workflow_refine_pass, 1)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn("Spy refined.", text)

    def test_skip_workflow_refine_skips_refine_pass(self) -> None:
        register_modality(_RefineModality())
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, REFINE_MODALITY_ID, True, Storage(root))
            skip_sent = False

            async def on_event(payload: dict[str, object]) -> None:
                nonlocal skip_sent
                if (
                    not skip_sent
                    and payload.get("type") == "workflow"
                    and payload.get("action") == "plan"
                ):
                    steps = payload.get("steps")
                    if isinstance(steps, list):
                        step_dicts = [
                            cast(dict[str, object], s)
                            for s in cast(list[object], steps)
                            if isinstance(s, dict)
                        ]
                    else:
                        step_dicts = []
                    step_id = refine_step_id(REFINE_MODALITY_ID)
                    if any(s.get("id") == step_id for s in step_dicts):
                        runner.signal_action(step_id, "skip")
                        skip_sent = True

            runner = WorkflowRunner(on_event=on_event)

            refined = GenerationArtifacts(
                segments=[GenerationSegment("prose", "Refined.\n")]
            )

            async def _fake_refine(*_a: object, **_k: object) -> GenerationArtifacts:
                return refined

            async def _draft(*_a: object, **_k: object) -> str:
                return "Draft only.\n"

            async def _run() -> None:
                with patch("lens.core.operator.run_llm", mock_run_llm(_draft)):
                    with patch(
                        "lens.core.modalities.workflow.run_refine_pass",
                        new=AsyncMock(side_effect=_fake_refine),
                    ) as mock_refine:
                        with contextlib.redirect_stdout(io.StringIO()):
                            with contextlib.redirect_stderr(io.StringIO()):
                                await WriteOperator.run_inline(
                                    session=ProjectSession(root, root),
                                    narrative=narrative,
                                    prompt="go",
                                    pins=[],
                                    unpins=[],
                                    llm_id="mock",
                                    retry=False,
                                    workflow=runner,
                                )
                        mock_refine.assert_not_called()

            asyncio.run(_run())
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn("Draft only.", text)
            self.assertNotIn("Refined.", text)
