"""Hook contract and registry for orchestration hooks.

Each hook follows ``should_run(ctx) -> bool`` + ``run(ctx) -> Any``.
Hooks register via ``register_hook()`` and are invoked by ``run_hooks()``.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookContext:
    session: ProjectSession
    narrative: NarrativeNode
    cursor: NarrativeNode | None = None
    operator_name: str | None = None
    trigger: Literal["post_inline", "summarize_close"] | None = None
    on_token: Callable[[str], Awaitable[None]] | None = None
    cancel_event: asyncio.Event | None = None
    on_status: Callable[[str], None] | None = None
    on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    extra: dict[str, object] = field(default_factory=dict[str, object])


class Hook(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def should_run(self, ctx: HookContext) -> bool: ...

    @abstractmethod
    async def run(self, ctx: HookContext) -> Any: ...

    @property
    def failure_policy(self) -> Literal["fatal", "warn"]:
        return "fatal"


_HOOKS: list[Hook] = []


def register_hook(hook: Hook) -> None:
    _HOOKS.append(hook)


def clear_hooks() -> None:
    _HOOKS.clear()


def get_registered_hooks() -> list[Hook]:
    return list(_HOOKS)


async def run_hooks(ctx: HookContext) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for hook in _HOOKS:
        try:
            if hook.should_run(ctx):
                result = await hook.run(ctx)
                results[hook.name] = result
        except Exception:
            if hook.failure_policy == "fatal":
                raise
            _log.warning("hook %s failed (warn policy):", hook.name, exc_info=True)
    return results


def register_default_hooks() -> None:
    """Register all built-in hooks.  Idempotent — safe to call multiple times."""
    existing = {h.name for h in _HOOKS}
    from lens.core.hooks_auto_compress import AutoCompressHook

    if "auto_compress" not in existing:
        register_hook(AutoCompressHook())
    from lens.core.hooks_remember import RememberHook

    if "remember" not in existing:
        register_hook(RememberHook())
