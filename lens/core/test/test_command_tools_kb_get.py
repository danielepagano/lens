"""``kb_get`` handler: design modules arrive with their authoring template.

Tag search finds ``design.*`` objects and never their templates — a template is
not a design object and is not tagged as one.  So the runtime path that
discovers a module has to supply the other half itself, the way ``--module``
already does at crawl time.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.command_tools import get_command_registry
from lens.core.knowledge import KnowledgeStore


def _make_project(tmp: Path) -> Path:
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
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _write(root: Path, kb_id: str, text: str) -> None:
    obj_type, key = kb_id.split(".", 1)
    folder = root / "knowledge" / obj_type
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.md").write_text(text, encoding="utf-8")


def _get(root: Path, ids: list[str]) -> str:
    """Call ``kb_get`` the way an operator does — through the registry."""
    _tool_def, handler = get_command_registry()["kb_get"]

    async def _run() -> str:
        return await handler({"ids": ids}, root)

    return asyncio.run(_run())


class TestKbGetDesignTemplateCompanion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        KnowledgeStore.clear_registry()
        self.root = _make_project(Path(self._tmp.name))

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def test_design_module_brings_its_template(self) -> None:
        _write(self.root, "design.clock", "CLOCK MODULE\n")
        _write(self.root, "clock._template", "CLOCK TEMPLATE\n")

        out = _get(self.root, ["design.clock"])

        self.assertIn("CLOCK MODULE", out)
        self.assertIn("CLOCK TEMPLATE", out)

    def test_no_template_is_not_an_error(self) -> None:
        _write(self.root, "design.world", "WORLD MODULE\n")

        out = _get(self.root, ["design.world"])

        self.assertIn("WORLD MODULE", out)
        self.assertNotIn("_template", out)

    def test_several_modules_each_bring_their_own(self) -> None:
        _write(self.root, "design.encounter", "ENCOUNTER MODULE\n")
        _write(self.root, "encounter._template", "ENCOUNTER TEMPLATE\n")
        _write(self.root, "design.clock", "CLOCK MODULE\n")
        _write(self.root, "clock._template", "CLOCK TEMPLATE\n")

        out = _get(self.root, ["design.encounter", "design.clock"])

        for expected in (
            "ENCOUNTER MODULE",
            "ENCOUNTER TEMPLATE",
            "CLOCK MODULE",
            "CLOCK TEMPLATE",
        ):
            self.assertIn(expected, out)

    def test_link_expansion_suffix_still_resolves_the_template(self) -> None:
        _write(self.root, "design.clock", "CLOCK MODULE\n")
        _write(self.root, "clock._template", "CLOCK TEMPLATE\n")

        out = _get(self.root, ["design.clock+"])

        self.assertIn("CLOCK TEMPLATE", out)

    def test_rules_objects_do_not_drag_in_authoring_templates(self) -> None:
        """``rules.encounter`` is the play-time booklet, not an authoring aid."""
        _write(self.root, "rules.encounter", "HOW TO RUN ONE\n")
        _write(self.root, "encounter._template", "ENCOUNTER TEMPLATE\n")

        out = _get(self.root, ["rules.encounter"])

        self.assertIn("HOW TO RUN ONE", out)
        self.assertNotIn("ENCOUNTER TEMPLATE", out)

    def test_other_types_are_untouched(self) -> None:
        _write(self.root, "npc.velthor", "A WIZARD\n")
        _write(self.root, "velthor._template", "SHOULD NOT APPEAR\n")

        out = _get(self.root, ["npc.velthor"])

        self.assertIn("A WIZARD", out)
        self.assertNotIn("SHOULD NOT APPEAR", out)


if __name__ == "__main__":
    unittest.main()
