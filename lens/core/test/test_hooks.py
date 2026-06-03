"""Unit tests for orchestration hook registry and built-in hooks."""

from __future__ import annotations

import asyncio
import unittest
from typing import Literal

from lens.core import hooks as hooks_mod
from lens.core.hooks import (
    Hook,
    HookContext,
    clear_hooks,
    get_registered_hooks,
    register_hook,
    run_hooks,
)
from lens.core.hooks_auto_compress import AutoCompressHook
from lens.core.hooks_remember import RememberHook


# ---------------------------------------------------------------------------
# Save/restore global registry for test isolation
# ---------------------------------------------------------------------------

_saved: list[Hook] = []


def _save() -> None:
    global _saved
    _saved = get_registered_hooks()


def _restore() -> None:
    clear_hooks()
    for h in _saved:
        register_hook(h)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _EchoHook(Hook):
    def __init__(self, name: str, key: str = "echo") -> None:
        self._name = name
        self._key = key

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, ctx: HookContext) -> bool:
        return True

    async def run(self, ctx: HookContext) -> str:
        return str(ctx.extra.get(self._key, ""))


class _ConditionalHook(Hook):
    def __init__(self, name: str, key: str = "flag") -> None:
        self._name = name
        self._key = key

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, ctx: HookContext) -> bool:
        return bool(ctx.extra.get(self._key))

    async def run(self, ctx: HookContext) -> str:
        return f"{self._name}-ran"


class _RaisingHook(Hook):
    def __init__(self, name: str, policy: Literal["fatal", "warn"] = "fatal") -> None:
        self._name = name
        self._policy: Literal["fatal", "warn"] = policy

    @property
    def name(self) -> str:
        return self._name

    @property
    def failure_policy(self) -> Literal["fatal", "warn"]:
        return self._policy

    def should_run(self, ctx: HookContext) -> bool:
        return True

    async def run(self, ctx: HookContext) -> str:
        raise ValueError(f"{self._name} failed intentionally")


def _sync(ctx: HookContext) -> dict[str, str]:
    return asyncio.run(run_hooks(ctx))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHookRegistry(unittest.TestCase):
    def setUp(self) -> None:
        _save()
        clear_hooks()

    def tearDown(self) -> None:
        _restore()

    def test_register_and_run(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_EchoHook("e", key="msg"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock(), extra={"msg": "hi"})
        self.assertEqual(_sync(ctx), {"e": "hi"})

    def test_conditional_skips_when_false(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_ConditionalHook("c", key="go"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock(), extra={"go": False})
        self.assertEqual(_sync(ctx), {})

    def test_conditional_runs_when_true(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_ConditionalHook("c", key="go"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock(), extra={"go": True})
        self.assertEqual(_sync(ctx), {"c": "c-ran"})

    def test_multiple_hooks(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_EchoHook("a", key="x"))
        register_hook(_EchoHook("b", key="y"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock(), extra={"x": "1", "y": "2"})
        self.assertEqual(_sync(ctx), {"a": "1", "b": "2"})

    def test_clear_removes_all(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_EchoHook("a"))
        clear_hooks()
        ctx = HookContext(session=MagicMock(), narrative=MagicMock())
        self.assertEqual(_sync(ctx), {})

    def test_fatal_policy_raises(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_RaisingHook("boom", policy="fatal"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock())
        with self.assertRaises(ValueError):
            _sync(ctx)

    def test_warn_policy_swallows(self) -> None:
        from unittest.mock import MagicMock

        register_hook(_RaisingHook("boom", policy="warn"))
        ctx = HookContext(session=MagicMock(), narrative=MagicMock())
        self.assertEqual(_sync(ctx), {})

    def test_register_default_hooks(self) -> None:
        clear_hooks()
        hooks_mod.register_default_hooks()
        self.assertEqual(len(get_registered_hooks()), 2)


# ---------------------------------------------------------------------------
# AutoCompressHook
# ---------------------------------------------------------------------------

class TestAutoCompressHookUnit(unittest.TestCase):
    def test_skips_when_not_post_inline(self) -> None:
        from unittest.mock import MagicMock

        h = AutoCompressHook()
        for trigger in (None, "summarize_close"):
            ctx = HookContext(
                session=MagicMock(), narrative=MagicMock(),
                operator_name="write", trigger=trigger,
            )
            self.assertFalse(h.should_run(ctx))

    def test_skips_non_inline_operators(self) -> None:
        from unittest.mock import MagicMock

        h = AutoCompressHook()
        for op in ("edit", "design", "section", "collate", "compress", "advance"):
            ctx = HookContext(
                session=MagicMock(), narrative=MagicMock(),
                operator_name=op, trigger="post_inline",
            )
            self.assertFalse(h.should_run(ctx))


# ---------------------------------------------------------------------------
# RememberHook
# ---------------------------------------------------------------------------

class TestRememberHookUnit(unittest.TestCase):
    def test_skips_when_not_summarize_close(self) -> None:
        h = RememberHook()
        for trigger in (None, "post_inline"):
            ctx = HookContext(
                session=None,  # type: ignore[arg-type]
                narrative=None,  # type: ignore[arg-type]
                trigger=trigger,
            )
            self.assertFalse(h.should_run(ctx))

    def test_no_pinned_ids_returns_false(self) -> None:
        h = RememberHook()
        ctx = HookContext(
            session=None,  # type: ignore[arg-type]
            narrative=None,  # type: ignore[arg-type]
            trigger="summarize_close",
            extra={"crawl_result": None},
        )
        self.assertFalse(h.should_run(ctx))


# ---------------------------------------------------------------------------
# Integration: hook fires through real operator paths
# ---------------------------------------------------------------------------

class TestHookThroughOperator(unittest.TestCase):
    """Verify hooks reach the real compress/remember functions via operator paths."""

    def setUp(self) -> None:
        _save()
        clear_hooks()

    def tearDown(self) -> None:
        _restore()

    def test_auto_compress_fires_via_registry(self) -> None:
        """AutoCompressHook fires when run_hooks is called with post_inline trigger."""
        from unittest.mock import AsyncMock, MagicMock, patch

        h = AutoCompressHook()
        register_hook(h)

        state = MagicMock()
        state.compress_on = True
        state.trigger = MagicMock()

        with (
            patch("lens.core.hooks_auto_compress.read_cursor_auto_compress_state", return_value=state),
            patch("lens.core.hooks_auto_compress.maybe_post_main_auto_compress", new_callable=AsyncMock) as mock_compress,
        ):
            ctx = HookContext(
                session=MagicMock(), narrative=MagicMock(),
                operator_name="write", trigger="post_inline",
            )
            _sync(ctx)
            mock_compress.assert_awaited_once()

    def test_auto_compress_skipped_on_summarize_close(self) -> None:
        """AutoCompressHook.should_run returns False for summarize_close trigger."""
        from unittest.mock import MagicMock

        h = AutoCompressHook()
        ctx = HookContext(
            session=MagicMock(),
            narrative=MagicMock(),
            operator_name="chat",
            trigger="summarize_close",
        )
        self.assertFalse(h.should_run(ctx))

    def test_remember_fires_through_run_hooks_via_registry(self) -> None:
        """RememberHook fires when run_hooks is called with a remember context."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from lens.core.context import CrawlResult

        register_hook(RememberHook())

        crawl_result = MagicMock(spec=CrawlResult)
        crawl_result.pinned_ids = ["remember.test"]

        store = MagicMock()
        store.get_objects.return_value = {
            "remember.test": MagicMock(tags=["remember.test"])
        }

        with patch("lens.core.knowledge.KnowledgeStore.for_project", return_value=store):
            with patch("lens.core.hooks_remember.apply_remember_patches", new_callable=AsyncMock) as mock_apply:
                mock_apply.return_value = "remembered"

                ctx = HookContext(
                    session=MagicMock(),
                    narrative=MagicMock(),
                    operator_name="section",
                    trigger="summarize_close",
                    extra={
                        "crawl_result": crawl_result,
                        "content": "some content",
                    },
                )
                results = _sync(ctx)
                self.assertIn("remember", results)
                mock_apply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
