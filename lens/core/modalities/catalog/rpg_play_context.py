"""Play: auto-pin the core RPG rules.

Type companions (``rules.<type>`` for every ``<type>.*`` object in scope) used
to be contributed here too, which silently made them a ``play``-only feature.
They are engine behaviour now and run inside :func:`~lens.core.context.crawl`
for every operator; what stays here is the part that really is RPG-specific —
the two booklets a play beat is always run against.
"""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import CrawlContribution, ModalityContext

PLAY_AUTO_PINS: tuple[str, ...] = ("rules.system", "rules.rpg")


class RpgPlayContextModality(Modality):
    id = "rpg_play_context"

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        if ctx.operator_name != "play":
            return CrawlContribution()
        return CrawlContribution(extra_pins=PLAY_AUTO_PINS)


register_modality(RpgPlayContextModality())
