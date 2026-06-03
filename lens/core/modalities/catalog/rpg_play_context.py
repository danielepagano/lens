"""Play: auto-pin core rules + rules-type companions for pinned objects."""

from __future__ import annotations

from lens.core.crawl_transforms import RulesCompanionTransform
from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import storage_for_ctx
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import CrawlContribution, ModalityContext

PLAY_AUTO_PINS: tuple[str, ...] = ("rules.system", "rules.rpg")


class RpgPlayContextModality(Modality):
    id = "rpg_play_context"

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        if ctx.operator_name != "play":
            return CrawlContribution()
        storage = storage_for_ctx(ctx)
        return CrawlContribution(
            extra_pins=PLAY_AUTO_PINS,
            transforms=(
                RulesCompanionTransform(
                    project_root=ctx.project_root,
                    storage=storage,
                ),
            ),
        )


register_modality(RpgPlayContextModality())
