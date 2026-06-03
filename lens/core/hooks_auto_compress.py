"""Auto-compress hook: runs after write/play/chat inline generation."""

from __future__ import annotations

from typing import Literal

from lens.core.auto_compress import (
    maybe_post_main_auto_compress,
    read_cursor_auto_compress_state,
)
from lens.core.hooks import Hook, HookContext


class AutoCompressHook(Hook):
    @property
    def name(self) -> str:
        return "auto_compress"

    @property
    def failure_policy(self) -> Literal["fatal", "warn"]:
        return "warn"

    def should_run(self, ctx: HookContext) -> bool:
        if ctx.trigger != "post_inline":
            return False
        if ctx.operator_name not in ("write", "play", "chat"):
            return False
        state = read_cursor_auto_compress_state(ctx.session, ctx.narrative)
        return bool(state.compress_on and state.trigger is not None)

    async def run(self, ctx: HookContext) -> None:
        await maybe_post_main_auto_compress(
            ctx.session,
            ctx.narrative,
            on_token=ctx.on_token,
            cancel_event=ctx.cancel_event,
            on_status=ctx.on_status,
            on_info_event=ctx.on_info_event,
        )
