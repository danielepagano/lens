"""Integration: a mention's lifetime across consecutive `write` invocations.

The unit tests in ``lens/core/test/test_mentions.py`` cover parsing, expiry and
in-place rendering in isolation.  This exercises the property that motivates the
whole design end to end: a mention is in the prompt on the turn it was asked
for, gone on the next, and everything before it is byte-identical either way —
so adding one does not invalidate the cacheable prefix.

Run with::

    poe test-integration
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import patch

from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.narrative import NarrativeNode
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession
from lens.core.test.llm_run_mock import mock_run_llm

_T = TypeVar("_T")


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
        io.StringIO()
    ):
        return asyncio.run(coro)


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


class TestMentionLifetimeAcrossTurns(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lens_itest_mentions_")
        tmp = Path(self._tmp.name)
        _git(tmp, "init")
        _git(tmp, "config", "user.email", "t@t.com")
        _git(tmp, "config", "user.name", "T")
        (tmp / ".gitkeep").write_text("", encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-m", "init")

        (tmp / "lens.toml").write_text(
            '[project]\nnarrative = "story"\n'
            '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n',
            encoding="utf-8",
        )
        narrative_dir = tmp / "narrative" / "story"
        narrative_dir.mkdir(parents=True)
        (narrative_dir / "_node.md").write_text("# story\n", encoding="utf-8")
        for kb_id, body in (
            ("person.amy", "Amy the merchant."),
            ("rules.haggling", "Haggling costs one hour."),
        ):
            type_name, key = kb_id.split(".", 1)
            d = tmp / "knowledge" / type_name
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.md").write_text(f"{body}\n", encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-m", "project")

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self.root = tmp
        self.session = ProjectSession(tmp, tmp)
        self.narrative = NarrativeNode(narrative_root=narrative_dir, key_path=())
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def _write(self, prompt: str, **kwargs: Any) -> None:
        captured = self.prompts

        async def _generate(
            messages: list[dict[str, str]], *_a: Any, **_k: Any
        ) -> str:
            # Joined, because once the node parses into turns the prompt is
            # spread across several messages rather than one user block.
            captured.append(
                "\n\n".join(m["content"] for m in messages if m["role"] != "system")
            )
            return "Generated prose."

        with patch("lens.core.operator.run_llm", mock_run_llm(_generate)):
            _run_async(
                WriteOperator.run_inline(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=prompt,
                    pins=[],
                    unpins=[],
                    llm_id=None,
                    retry=False,
                    **kwargs,
                )
            )

    def test_mention_is_present_for_one_turn_then_gone(self) -> None:
        self._write("Set the scene")
        self._write("Amy arrives, see @person.amy")
        self._write("She leaves")

        first, mentioned, after = self.prompts

        self.assertNotIn("Amy the merchant.", first)
        self.assertIn("KB['person.amy']", mentioned)
        self.assertIn("Amy the merchant.", mentioned)
        # One assistant turn later it stops expanding — nothing was deleted, the
        # annotation is still on disk for rewind to find.
        self.assertNotIn("Amy the merchant.", after)
        text = self.narrative.find_cursor().md_path().read_text(encoding="utf-8")
        self.assertIn("mention:", text)

    def test_include_survives_later_turns(self) -> None:
        self._write("Set the scene")
        self._write("Now haggle", includes=["rules.haggling"])
        self._write("Keep going")

        first, included, after = self.prompts

        self.assertNotIn("Haggling costs one hour.", first)
        self.assertIn("Haggling costs one hour.", included)
        self.assertIn("Haggling costs one hour.", after)

    def test_mention_does_not_land_in_the_knowledge_block(self) -> None:
        self._write("Amy arrives, see @person.amy")

        prompt = self.prompts[0]

        self.assertIn("KB['person.amy']", prompt)
        self.assertNotIn("RELEVANT KNOWLEDGE", prompt)
        self.assertLess(prompt.index("KB['person.amy']"), prompt.index("TASK"))

    def test_adding_a_mention_appends_rather_than_rewrites(self) -> None:
        """The cache-friendliness claim, checked rather than asserted.

        Expanding at the mention's own line means the transcript above it is
        untouched — which is the entire reason not to put mentions in
        ``[RELEVANT KNOWLEDGE]``, where every new one rewrites the whole prefix.
        """
        self._write("Set the scene")
        self._write("Continue")
        self._write("Amy arrives, see @person.amy")

        _, before, mentioned = self.prompts
        transcript = "Generated prose."

        self.assertIn(transcript, before)
        self.assertNotIn("KB['person.amy']", before)
        # Same transcript text, still ahead of the block the mention added.
        self.assertIn(transcript, mentioned)
        self.assertLess(
            mentioned.index(transcript), mentioned.index("KB['person.amy']")
        )


if __name__ == "__main__":
    unittest.main()
