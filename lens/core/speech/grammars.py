"""Speech markup grammars for TTS-oriented annotation in generated text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lens.core.speech.backend import SpeechError


@dataclass(frozen=True, slots=True)
class TtsGrammar:
    id: str
    rules_prompt_key: str
    tag_detect: re.Pattern[str]
    generate_prompt_key: str | None = None
    refine_prompt_key: str | None = None
    refine_system_prompt_key: str | None = None


_REGISTRY: dict[str, TtsGrammar] = {}


def register_tts_grammar(grammar: TtsGrammar) -> None:
    _REGISTRY[grammar.id] = grammar


def get_tts_grammar(grammar_id: str) -> TtsGrammar | None:
    return _REGISTRY.get(grammar_id)


def get_tts_grammar_or_raise(grammar_id: str) -> TtsGrammar:
    g = _REGISTRY.get(grammar_id)
    if g is None:
        raise KeyError(f"unknown TTS grammar {grammar_id!r}")
    return g


def registered_tts_grammar_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


def clear_tts_grammar_registry_for_tests() -> None:
    _REGISTRY.clear()


def resolve_tts_grammar(grammar_id: str | None) -> TtsGrammar | None:
    if not grammar_id:
        return None
    ensure_builtin_tts_grammars_registered()
    grammar = get_tts_grammar(grammar_id)
    if grammar is None:
        raise SpeechError(
            f"unknown [[speech]] grammar={grammar_id!r}; "
            f"supported: {sorted(_REGISTRY)}"
        )
    return grammar


def ensure_builtin_tts_grammars_registered() -> None:
    """Register shipped grammars (id → rules prompt key + line tag heuristic)."""
    if _REGISTRY:
        return
    register_tts_grammar(
        TtsGrammar(
            id="xai",
            rules_prompt_key="speech.grammar.xai.rules",
            tag_detect=re.compile(r"<[^>\n]+>|\[[^\]\n]+\]"),
        )
    )
    register_tts_grammar(
        TtsGrammar(
            id="gemini",
            rules_prompt_key="speech.grammar.gemini.rules",
            tag_detect=re.compile(r"\[[^\]\n]+\]"),
        )
    )
