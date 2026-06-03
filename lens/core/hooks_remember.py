"""Remember hook: applies kb_patch updates when closing sessions/sections/collates."""

from __future__ import annotations

from typing import Literal, cast

from lens.core.context import CrawlResult
from lens.core.hooks import Hook, HookContext
from lens.core.knowledge import KnowledgeStore
from lens.core.operators.session import apply_remember_patches
from lens.core.storage import Storage


class RememberHook(Hook):
    @property
    def name(self) -> str:
        return "remember"

    @property
    def failure_policy(self) -> Literal["fatal", "warn"]:
        return "warn"

    def should_run(self, ctx: HookContext) -> bool:
        if ctx.trigger != "summarize_close":
            return False
        crawl_result = cast("CrawlResult | None", ctx.extra.get("crawl_result"))
        if crawl_result is None or not crawl_result.pinned_ids:
            return False
        store = KnowledgeStore.for_project(ctx.session.project_root)
        pinned_objects = store.get_objects(crawl_result.pinned_ids)
        return any(
            any(t.startswith("remember.") for t in obj.tags)
            for obj in pinned_objects.values()
        )

    async def run(self, ctx: HookContext) -> str:
        crawl_result = cast("CrawlResult", ctx.extra["crawl_result"])
        content = cast("str", ctx.extra["content"])
        llm_id = cast("str | None", ctx.extra.get("llm_id"))
        reasoning = cast("str | None", ctx.extra.get("reasoning"))
        storage = cast("Storage | None", ctx.extra.get("storage"))
        return await apply_remember_patches(
            crawl_result=crawl_result,
            content=content,
            project_root=ctx.session.project_root,
            llm_id=llm_id,
            reasoning=reasoning,
            cancel_event=ctx.cancel_event,
            storage=storage,
        )
