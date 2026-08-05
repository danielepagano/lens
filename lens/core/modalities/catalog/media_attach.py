"""Media attach modality: post-response facet classification and VN-style image attach.

Selection loop (see issue #51): an ``anchor`` media search query (front matter
``modalities.media_attach.anchor``) narrows a media library to a subject; any facet with
more than one distinct value across the matches is undecided and offered to a
small, fast classify LLM alongside the previous selection (hysteresis) and a
little context. The chosen facet values are re-run against the anchor to pick
a winner, which is attached *before* the response text — exactly where a
manual VN attach would go — with the chosen facets recorded immediately above
the embed as a ``[facets: ...]: #`` annotation (see ``lens.core.media.facets``
for why that form and not an HTML comment).

The whole loop only has something to do when at least one facet varies across
the anchor's matches — a match set with no ``facets`` metadata at all can
never produce a decision. Rather than leave that to the front-matter anchor
(easy to configure without and get a silent no-op), every anchor search this
modality runs is executed with a hard-coded, non-optional ``facets!`` term
appended (see ``_faceted_query`` below) — front matter never needs to specify
it, and cannot omit it. That still leaves one no-op case a required-key term
can't rule out: several matches that all carry facets, but with identical
values across the board (nothing actually varies) — ``gates()`` calls that
out with its own reason rather than reporting active with nothing to do.

The main generation model never sees any of this: ``prompt_addenda`` is
deliberately empty, and the facet vocabulary reaches the classify model only
through its own isolated ``RefinePassSpec`` instruction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from lens.core.annotations import strip_markdown_comments
from lens.core.commands.attach import build_embed, build_layered_embed
from lens.core.exceptions import MediaSearchCapacityExceeded
from lens.core.media.attach_config import MediaAttachConfig
from lens.core.media.facets import (
    build_facets_annotation,
    facet_query_terms,
    find_last_facets,
)
from lens.core.media.service import MediaService
from lens.core.modalities.base import Modality
from lens.core.modalities.json_output import find_json_object
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import (
    MediaAttachCache,
    ModalityContext,
    ModalityGateResult,
    RefineApplyResult,
    RefinePassSpec,
)
from lens.core.mount_embed_strip import strip_standalone_lens_mount_attachment_lines
from lens.core.pinning import collect_modalities_fm
from lens.core.prompts import PromptStore
from lens.core.speech.playback_sequence import parse_composite_line

_log = logging.getLogger(__name__)

_SEARCH_PAGE_LIMIT = 20  # mirrors lens.core.media.search.PAGE_SIZE

_FACETS_REQUIRED_TERM = "facets!"


def _faceted_query(anchor: str) -> str:
    """Anchor query with a hard-coded, non-optional ``facets!`` term appended.

    Every search this modality runs goes through here rather than trusting
    the front-matter anchor to include it: a match set with no ``facets``
    metadata at all can never produce a decision (see module docstring), and
    that's worth ruling out at the query level rather than a silent no-op
    several steps downstream. Front matter never needs to spell this out,
    and duplicating it there (or in a hand-typed anchor) is harmless --
    required terms are AND'd, so a repeated one is a no-op.
    """
    return f"{anchor} {_FACETS_REQUIRED_TERM}"


def _read_node_text(ctx: ModalityContext) -> str:
    if not ctx.focus_node.exists():
        return ""
    return ctx.focus_node.md_path().read_text(encoding="utf-8")


def _previous_composite_background(node_text: str) -> str | None:
    for line in reversed(node_text.split("\n")):
        parsed = parse_composite_line(line)
        if parsed is not None:
            return parsed[0]
    return None


def _all_matches_are_foreground(service: MediaService, anchor: str) -> bool:
    """``True`` only when every anchor match (not just page 1) is ``composite: foreground``."""
    page = service.search(anchor)
    if page.total_items == 0 or page.total_items > len(page.items):
        return False
    for item in page.items:
        if service.get_metadata(item.relative_path).composite_role() != "foreground":
            return False
    return True


def _context_beats_text(node_text: str, beats: int) -> str:
    """Last *beats* blank-line-separated paragraphs of *node_text*, LLM-visible only."""
    if beats <= 0:
        return ""
    visible = strip_standalone_lens_mount_attachment_lines(strip_markdown_comments(node_text))
    paragraphs = [p.strip() for p in visible.split("\n\n") if p.strip()]
    return "\n\n".join(paragraphs[-beats:])


def build_classify_instruction(
    project_root: Path,
    *,
    facet_options: dict[str, frozenset[str]],
    current_facets: dict[str, str],
    context_text: str,
    target_text: str,
) -> str:
    prompts = PromptStore(project_root)
    facet_options_json = json.dumps(
        {key: sorted(values) for key, values in facet_options.items()}, ensure_ascii=False
    )
    current_facets_json = json.dumps(current_facets, ensure_ascii=False)
    return prompts.format(
        "modalities.media_attach.classify",
        facet_options_json=facet_options_json,
        current_facets_json=current_facets_json,
        context_text=context_text,
        target_text=target_text,
    )


def parse_classify_facets(raw: str) -> dict[str, str] | None:
    """Parse ``{"facets": {...}}``; tolerate a fence or short preamble before JSON."""
    data = find_json_object(raw)
    if data is None:
        return None
    facets_val = data.get("facets")
    if not isinstance(facets_val, dict):
        return None
    out: dict[str, str] = {}
    for key, value in facets_val.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str) or not isinstance(value, str):
            return None
        out[key] = value
    return out


def select_chosen_facets(
    parsed: dict[str, str], undecided: dict[str, frozenset[str]]
) -> dict[str, str]:
    """Keep only pairs whose key is undecided and whose value is in that facet's closed set."""
    return {
        key: value
        for key, value in parsed.items()
        if key in undecided and value in undecided[key]
    }


def apply_media_attach(
    model_output: str,
    *,
    service: MediaService,
    anchor: str,
    undecided: dict[str, frozenset[str]],
    previous_facets: dict[str, str],
    previous_bg: str | None,
    text: str,
) -> RefineApplyResult:
    """Classify, re-search, and prepend the attach + facets annotation to *text*.

    A pick identical to *previous_facets* resolves to the same image as last time —
    re-emitting the same annotation and embed would be pure noise with no visual
    change, so this is treated as a normal no-op (``applied=True``, *text* returned
    unchanged) rather than a warning.
    """
    parsed = parse_classify_facets(model_output)
    if parsed is None:
        warning = "media_attach: could not parse JSON output"
        _log.warning("%s", warning)
        return RefineApplyResult(text=text, applied=False, warnings=(warning,))

    chosen = select_chosen_facets(parsed, undecided)
    if not chosen:
        warning = "media_attach: no valid facet selections in model output"
        _log.warning("%s", warning)
        return RefineApplyResult(text=text, applied=False, warnings=(warning,))

    if chosen == previous_facets:
        return RefineApplyResult(text=text, applied=True)

    query = " ".join([anchor, *facet_query_terms(chosen)])
    page = service.search(query)
    if not page.items:
        warning = "media_attach: re-run search returned no results"
        _log.warning("%s", warning)
        return RefineApplyResult(text=text, applied=False, warnings=(warning,))

    winner = page.items[0].relative_path
    meta = service.get_metadata(winner)
    role = meta.composite_role()

    if role == "foreground":
        if not previous_bg:
            warning = "media_attach: chosen image is foreground-only and no previous background exists"
            _log.warning("%s", warning)
            return RefineApplyResult(text=text, applied=False, warnings=(warning,))
        embed = build_layered_embed(previous_bg, winner)
    else:
        embed = build_embed(winner, meta.extension)

    annotation = build_facets_annotation(chosen)
    prefix = f"{annotation}\n\n{embed}\n\n"
    return RefineApplyResult(text=prefix + text, applied=True)


class MediaAttachModality(Modality):
    id = "media_attach"

    def prepare_context(self, ctx: ModalityContext) -> ModalityContext:
        if ctx.media_attach is not None:
            return ctx

        config = MediaAttachConfig.from_project(ctx.project_root)
        fm = collect_modalities_fm(ctx.focus_node).get(self.id, {})
        anchor_raw = fm.get("anchor")
        anchor = anchor_raw.strip() if isinstance(anchor_raw, str) and anchor_raw.strip() else None
        search_anchor = _faceted_query(anchor) if anchor else None

        try:
            service = MediaService.for_project(ctx.project_root)
        except Exception:
            service = None

        mount_configured = service is not None
        vocabulary = None
        capacity_exceeded = False
        all_matches_foreground = False

        if service is not None and search_anchor:
            try:
                vocabulary = service.facet_vocabulary(search_anchor)
            except MediaSearchCapacityExceeded:
                capacity_exceeded = True
            except Exception:
                vocabulary = None
            if vocabulary is not None and vocabulary.match_count > 0:
                try:
                    all_matches_foreground = _all_matches_are_foreground(service, search_anchor)
                except Exception:
                    all_matches_foreground = False

        node_text = _read_node_text(ctx)
        previous_facets = find_last_facets(node_text)
        previous_bg = _previous_composite_background(node_text)

        cache = MediaAttachCache(
            config=config,
            anchor=anchor,
            search_anchor=search_anchor,
            mount_configured=mount_configured,
            vocabulary=vocabulary,
            capacity_exceeded=capacity_exceeded,
            all_matches_foreground=all_matches_foreground,
            previous_facets=previous_facets,
            previous_bg=previous_bg,
        )
        return replace(ctx, media_attach=cache)

    def gates(self, ctx: ModalityContext) -> ModalityGateResult:
        cache = ctx.media_attach
        if cache is None or not cache.mount_configured:
            return ModalityGateResult(active=False, reason="no mount_point configured in lens.toml")
        if not cache.anchor:
            return ModalityGateResult(
                active=False, reason="no modalities.media_attach.anchor in front matter"
            )
        if cache.capacity_exceeded:
            return ModalityGateResult(active=False, reason="media search index is over capacity")
        if cache.vocabulary is None or cache.vocabulary.match_count == 0:
            return ModalityGateResult(active=False, reason="anchor matches no media")
        if cache.vocabulary.match_count > 1 and not cache.vocabulary.undecided:
            return ModalityGateResult(
                active=False,
                reason=(
                    f"anchor matches {cache.vocabulary.match_count} images "
                    "but none differ on any facet"
                ),
            )
        if cache.all_matches_foreground and not cache.previous_bg:
            return ModalityGateResult(
                active=False,
                reason="every anchor match is a foreground composite and there is no background to build on",
            )
        return ModalityGateResult()

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        # Deliberately empty: the main generation model must never learn this
        # modality exists — facet selection happens only in the isolated refine pass.
        del ctx
        return ()

    def workflow_refine_pass(self, ctx: ModalityContext, text: str) -> RefinePassSpec | None:
        cache = ctx.media_attach
        if cache is None or cache.vocabulary is None or cache.search_anchor is None:
            return None
        undecided = cache.vocabulary.undecided
        if not undecided:
            return None

        service = MediaService.for_project(ctx.project_root)
        if service is None:
            return None

        node_text = _read_node_text(ctx)
        context_text = _context_beats_text(node_text, cache.config.context_beats)

        instruction = build_classify_instruction(
            ctx.project_root,
            facet_options=undecided,
            current_facets=cache.previous_facets,
            context_text=context_text,
            target_text=text,
        )
        prompts = PromptStore(ctx.project_root)
        system_message = prompts.get("modalities.media_attach.classify_system")

        anchor = cache.search_anchor
        previous_facets = cache.previous_facets
        previous_bg = cache.previous_bg

        def apply(model_output: str) -> RefineApplyResult:
            return apply_media_attach(
                model_output,
                service=service,
                anchor=anchor,
                undecided=undecided,
                previous_facets=previous_facets,
                previous_bg=previous_bg,
                text=text,
            )

        return RefinePassSpec(
            instruction=instruction,
            llm_id=cache.config.llm,
            system_message=system_message,
            apply=apply,
        )


register_modality(MediaAttachModality())
