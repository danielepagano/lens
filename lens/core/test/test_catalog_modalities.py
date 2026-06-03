"""Tests for shipped catalog modalities (resolution + primary hooks)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import CrawlResult, CrawlSpec
from lens.core.modalities import (
    apply_modality_crawl,
    apply_modality_prompt_addenda,
    clear_registry_for_tests,
    ensure_modalities_registered,
    registered_ids,
    resolve_modalities,
)
from lens.core.modalities.catalog.rpg_play_context import PLAY_AUTO_PINS
from lens.core.modalities.types import ModalityContext
from lens.core.narrative import NarrativeNode
from lens.core.operators.chat import ChatOperator
from lens.core.operators.design import DesignOperator
from lens.core.operators.write import WriteOperator
from lens.core.pinning import set_modality
from lens.core.prompts import PromptStore
from lens.core.storage import Storage
from lens.rpg.operators.play import PlayOperator


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


def _make_project(tmp: Path, *, datasets: str | None = None) -> tuple[Path, NarrativeNode]:
    ds = f'\ndatasets = [{datasets!r}]' if datasets else ""
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "test"{ds}\n')
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


class TestCatalogModalityResolution(unittest.TestCase):
    def test_clear_registry_reload_self_registers_shipped_catalog(self) -> None:
        ensure_modalities_registered()
        self.assertIn("markdown_fragment", registered_ids())
        clear_registry_for_tests()
        self.assertNotIn("markdown_fragment", registered_ids())
        ensure_modalities_registered()
        self.assertIn("markdown_fragment", registered_ids())

    def test_write_includes_builtin_stack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(_init_repo(Path(tmp)))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("markdown_fragment", resolved.active_ids)
            self.assertIn("md_html_comments", resolved.active_ids)

    def test_fm_opt_out_md_html_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality(narrative, "md_html_comments", False, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            self.assertIn("markdown_fragment", resolved.active_ids)
            self.assertNotIn("md_html_comments", resolved.active_ids)

    def test_chat_requires_attributed_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(_init_repo(Path(tmp)))
            resolved, _ = resolve_modalities(ChatOperator, narrative)
            self.assertIn("attributed_dialogue", resolved.active_ids)

    def test_design_requires_design_modalities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(_init_repo(Path(tmp)))
            resolved, _ = resolve_modalities(DesignOperator, narrative)
            for mid in ("kb_fence", "tool_fence_awareness"):
                self.assertIn(mid, resolved.active_ids)

    def test_play_requires_rpg_modalities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, narrative = _make_project(
                _init_repo(Path(tmp)), datasets="rpg"
            )
            resolved, _ = resolve_modalities(PlayOperator, narrative)
            self.assertIn("attributed_dialogue", resolved.active_ids)
            self.assertIn("rpg_play_context", resolved.active_ids)

class TestCatalogModalityHooks(unittest.TestCase):
    def test_builtin_prompt_addenda_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            cr = CrawlResult.from_text_fields(
                knowledge=[], previous_summaries=[], current_content=None
            )
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            ctx = ModalityContext(
                session=None,
                narrative=narrative,
                focus_node=narrative,
                operator_name="write",
                crawl_result=cr,
                params={},
                project_root=root,
            )
            messages = apply_modality_prompt_addenda(
                [{"role": "system", "content": "Base."}],
                resolved,
                ctx,
            )
            content = messages[0]["content"]
            prompts = PromptStore(root)
            self.assertIn(prompts.get("modalities.markdown_fragment.addendum"), content)
            self.assertIn(prompts.get("modalities.md_html_comments.rules"), content)

    def test_rpg_play_context_pins_and_rules_companion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            rules_dir = root / "knowledge" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (rules_dir / "encounter.md").write_text("Rules for encounter\n")
            pc_dir = root / "knowledge" / "pc"
            pc_dir.mkdir(parents=True, exist_ok=True)
            (pc_dir / "alice.md").write_text("Alice the PC\n")
            enc_dir = root / "knowledge" / "encounter"
            enc_dir.mkdir(parents=True, exist_ok=True)
            (enc_dir / "bridge.md").write_text("Bridge encounter\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "rules"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            _root, narrative = _make_project(root, datasets="rpg")
            spec = CrawlSpec.of(
                narrative,
                operator=PlayOperator,
                storage=Storage(root),
                extra_pins=["pc.alice", "encounter.bridge"],
            )
            merged, ctx, resolved = PlayOperator.crawl_with_modalities(
                spec, {}, session=None, narrative=narrative
            )
            apply_modality_crawl(merged, resolved, ctx)
            for pin in PLAY_AUTO_PINS:
                self.assertIn(pin, merged.pinned_ids)
            self.assertIn("rules.encounter", merged.pinned_ids)
