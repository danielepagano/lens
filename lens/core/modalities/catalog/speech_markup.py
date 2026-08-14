"""Speech engine markup modality: opt-in TTS tags and optional refine pass."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog.attributed_dialogue import split_attributed_dialogue_line
from lens.core.modalities.json_output import find_json_object
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import (
    ModalityContext,
    ModalityGateResult,
    RefineApplyResult,
    RefinePassSpec,
    SpeechMarkupCache,
)
from lens.core.pinning import collect_modalities_fm
from lens.core.prompts import PromptStore
from lens.core.speech import registry as speech_registry
from lens.core.speech.grammars import (
    TtsGrammar,
    ensure_builtin_tts_grammars_registered,
    resolve_tts_grammar,
)

_log = logging.getLogger(__name__)

SPEECH_MARKUP_MODES = frozenset({"generate", "refine", "both"})
"""``modalities.speech_markup.mode`` values: generate tags while writing, run the
post-generation refine pass, or both. Anything else falls back to ``both``."""


@dataclass(frozen=True, slots=True)
class SpeechMarkupLineRef:
    index: int
    prefix: str
    body: str


def split_lines_keepends(text: str) -> tuple[list[str], bool]:
    has_trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if has_trailing_newline:
        lines = lines[:-1]
    return lines, has_trailing_newline


def select_speech_markup_line_refs(
    lines: list[str],
    tag_detect: re.Pattern[str],
) -> list[SpeechMarkupLineRef]:
    """Lines to send to the refine model (full line in, full line out after merge)."""
    selected: list[SpeechMarkupLineRef] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        split = split_attributed_dialogue_line(line)
        if split is not None:
            selected.append(
                SpeechMarkupLineRef(index=i, prefix=split.prefix, body=split.body)
            )
            continue
        if tag_detect.search(line):
            selected.append(
                SpeechMarkupLineRef(index=i, prefix="", body=line.rstrip())
            )
    return selected


def encode_refine_lines_json(bodies: list[str]) -> str:
    return json.dumps({"lines": bodies}, ensure_ascii=False)


def parse_refine_lines_json(raw: str) -> list[str] | None:
    """Parse ``{"lines": ["…", …]}``; tolerate fences or a short preamble before JSON."""
    data = find_json_object(raw)
    if data is None:
        return None
    payload = cast(dict[str, object], data)
    lines_val = payload.get("lines")
    if not isinstance(lines_val, list):
        return None
    out: list[str] = []
    for item in cast(list[object], lines_val):
        if not isinstance(item, str):
            return None
        out.append(item)
    return out


def apply_refined_speech_markup(
    lines: list[str],
    refs: list[SpeechMarkupLineRef],
    refined_bodies: list[str],
    *,
    has_trailing_newline: bool,
) -> str:
    """Merge refined bodies back; return original text if body count mismatches."""
    if len(refined_bodies) != len(refs):
        return "\n".join(lines) + ("\n" if has_trailing_newline else "")

    out_lines = list(lines)
    for ref, new_body in zip(refs, refined_bodies, strict=True):
        if ref.prefix:
            out_lines[ref.index] = f"{ref.prefix}{new_body.rstrip()}"
        else:
            out_lines[ref.index] = new_body.rstrip()
    merged = "\n".join(out_lines)
    return merged + ("\n" if has_trailing_newline else "")


def apply_refined_speech_markup_from_model_output(
    lines: list[str],
    refs: list[SpeechMarkupLineRef],
    refined_text: str,
    *,
    has_trailing_newline: bool,
) -> RefineApplyResult:
    """Parse JSON refine output and merge; warn and keep original on failure."""
    original = "\n".join(lines) + ("\n" if has_trailing_newline else "")
    bodies = parse_refine_lines_json(refined_text)
    if bodies is None:
        warning = "speech refine: could not parse JSON output"
        _log.warning("%s", warning)
        return RefineApplyResult(
            text=original,
            applied=False,
            warnings=(warning,),
        )
    if len(bodies) != len(refs):
        warning = (
            "speech refine: line count mismatch "
            f"(model returned {len(bodies)} lines, expected {len(refs)})"
        )
        _log.warning("%s", warning)
        return RefineApplyResult(
            text=original,
            applied=False,
            warnings=(warning,),
        )
    merged = apply_refined_speech_markup(
        lines,
        refs,
        bodies,
        has_trailing_newline=has_trailing_newline,
    )
    return RefineApplyResult(text=merged, applied=True)


def speech_markup_generate_addendum(project_root: Path, grammar: TtsGrammar) -> str:
    prompts = PromptStore(project_root)
    rules = prompts.get(grammar.rules_prompt_key)
    key = grammar.generate_prompt_key or "speech.markup.generate"
    return prompts.format(key, grammar_rules=rules)


def build_refine_instruction(
    project_root: Path,
    grammar: TtsGrammar,
    bodies: list[str],
) -> str:
    prompts = PromptStore(project_root)
    rules = prompts.get(grammar.rules_prompt_key)
    key = grammar.refine_prompt_key or "speech.markup.refine"
    return prompts.format(
        key,
        grammar_rules=rules,
        lines_json=encode_refine_lines_json(bodies),
    )


class SpeechMarkupModality(Modality):
    id = "speech_markup"

    def prepare_context(self, ctx: ModalityContext) -> ModalityContext:
        if ctx.speech_markup is not None:
            return ctx
        ensure_builtin_tts_grammars_registered()
        try:
            descriptor = speech_registry.load_descriptor(ctx.project_root)
        except Exception:
            return ctx
        grammar = (
            resolve_tts_grammar(descriptor.grammar) if descriptor.grammar else None
        )
        fm = collect_modalities_fm(ctx.focus_node).get(self.id, {})
        mode = fm.get("mode")
        if mode not in SPEECH_MARKUP_MODES:
            mode = "both"
        cache = SpeechMarkupCache(descriptor=descriptor, grammar=grammar, mode=mode)
        return replace(ctx, speech_markup=cache)

    def gates(self, ctx: ModalityContext) -> ModalityGateResult:
        cache = ctx.speech_markup
        if cache is None:
            return ModalityGateResult(
                active=False, reason="[[speech]] is not configured"
            )
        if not cache.descriptor.grammar:
            return ModalityGateResult(
                active=False,
                reason="[[speech]] has no grammar= (required for speech_markup)",
            )
        if cache.grammar is None:
            return ModalityGateResult(
                active=False,
                reason=f"unknown [[speech]] grammar={cache.descriptor.grammar!r}",
            )
        return ModalityGateResult()

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        cache = ctx.speech_markup
        if cache is None or cache.grammar is None:
            return ()
        if cache.mode not in ("generate", "both"):
            return ()
        return (speech_markup_generate_addendum(ctx.project_root, cache.grammar),)

    def workflow_refine_pass(self, ctx: ModalityContext, text: str) -> RefinePassSpec | None:
        cache = ctx.speech_markup
        if cache is None or cache.grammar is None:
            return None
        if cache.mode not in ("refine", "both"):
            return None

        lines, has_trailing_newline = split_lines_keepends(text)
        refs = select_speech_markup_line_refs(lines, cache.grammar.tag_detect)
        if not refs:
            return None

        bodies = [ref.body for ref in refs]
        prompts = PromptStore(ctx.project_root)
        instruction = build_refine_instruction(ctx.project_root, cache.grammar, bodies)
        refine_sys_key = (
            cache.grammar.refine_system_prompt_key or "speech.markup.refine_system"
        )
        system_message = prompts.get(refine_sys_key)
        refine_llm_id = cache.descriptor.refine_llm_id

        def apply_refined(refined_text: str) -> RefineApplyResult:
            return apply_refined_speech_markup_from_model_output(
                lines,
                refs,
                refined_text,
                has_trailing_newline=has_trailing_newline,
            )

        return RefinePassSpec(
            instruction=instruction,
            llm_id=refine_llm_id,
            system_message=system_message,
            apply=apply_refined,
        )


register_modality(SpeechMarkupModality())
