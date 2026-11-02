"""Run-scoped prompt overrides: the A/B arm that cannot leak or be left behind."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from lens.core.prompts import PromptStore, load_prompt_override_files, run_prompt_overrides


class TestRunPromptOverrides(unittest.TestCase):
    def test_scoped_to_the_block(self) -> None:
        store = PromptStore(None)
        builtin = store.get("play.held_back")
        with run_prompt_overrides({"play.held_back": "B {triggers}"}):
            self.assertEqual(PromptStore(None).get("play.held_back"), "B {triggers}")
            self.assertEqual(PromptStore(None).resolve("play.held_back").source, "run")
        self.assertEqual(PromptStore(None).get("play.held_back"), builtin)

    def test_a_parallel_run_does_not_see_it(self) -> None:
        seen: dict[str, str] = {}

        async def arm(name: str, value: str | None) -> None:
            with run_prompt_overrides({"play.held_back": value} if value else None):
                await asyncio.sleep(0.01)
                seen[name] = PromptStore(None).get("play.held_back")

        async def both() -> None:
            await asyncio.gather(arm("b", "B {triggers}"), arm("a", None))

        asyncio.run(both())
        self.assertEqual(seen["b"], "B {triggers}")
        self.assertEqual(seen["a"], PromptStore(None).get("play.held_back"))

    def test_files_are_checked_before_the_run(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ok.txt").write_text("Held {triggers}\n")
        (tmp / "bad.txt").write_text("Held {nope}\n")
        self.assertEqual(
            load_prompt_override_files(["play.held_back=ok.txt"], tmp, None),
            {"play.held_back": "Held {triggers}"},
        )
        for spec, needle in (
            ("play.held_back=bad.txt", "placeholders: triggers"),
            ("no.such.key=ok.txt", "unknown prompt key"),
            ("play.held_back=missing.txt", "cannot read"),
            ("play.held_back", "expected KEY=FILE"),
        ):
            with self.assertRaises(ValueError, msg=spec) as caught:
                load_prompt_override_files([spec], tmp, None)
            self.assertIn(needle, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
