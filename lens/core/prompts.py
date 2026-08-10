from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
import tomllib

from lens.core.project import (
    get_selected_datasets,
    get_selected_prompt_pack,
    resolve_dataset_path,
)


@dataclass(frozen=True)
class PromptSpec:
    key: str
    variables: frozenset[str]


@dataclass(frozen=True)
class ResolvedPrompt:
    key: str
    value: str
    source: str


PROMPT_SPECS: dict[str, PromptSpec] = {
    "shared.formatting_addendum": PromptSpec("shared.formatting_addendum", frozenset()),
    "modalities.markdown_fragment.addendum": PromptSpec(
        "modalities.markdown_fragment.addendum", frozenset()
    ),
    "modalities.md_html_comments.rules": PromptSpec(
        "modalities.md_html_comments.rules", frozenset()
    ),
    "modalities.attributed_dialogue.rules": PromptSpec(
        "modalities.attributed_dialogue.rules", frozenset()
    ),
    "modalities.kb_fence.rules": PromptSpec("modalities.kb_fence.rules", frozenset()),
    "modalities.tool_fence_awareness.hint": PromptSpec(
        "modalities.tool_fence_awareness.hint", frozenset()
    ),
    "speech.markup.generate": PromptSpec(
        "speech.markup.generate", frozenset({"grammar_rules"})
    ),
    "speech.markup.refine_system": PromptSpec("speech.markup.refine_system", frozenset()),
    "speech.markup.refine": PromptSpec(
        "speech.markup.refine", frozenset({"grammar_rules", "lines_json"})
    ),
    "modalities.media_attach.classify_system": PromptSpec(
        "modalities.media_attach.classify_system", frozenset()
    ),
    "modalities.media_attach.classify": PromptSpec(
        "modalities.media_attach.classify",
        frozenset({"facet_options_json", "current_facets_json", "context_text", "target_text"}),
    ),
    "speech.grammar.xai.rules": PromptSpec("speech.grammar.xai.rules", frozenset()),
    "speech.grammar.gemini.rules": PromptSpec("speech.grammar.gemini.rules", frozenset()),
    "shared.retry_feedback_template": PromptSpec("shared.retry_feedback_template", frozenset({"feedback"})),
    "shared.block.relevant_knowledge": PromptSpec("shared.block.relevant_knowledge", frozenset()),
    "shared.block.previous_events_summary": PromptSpec("shared.block.previous_events_summary", frozenset()),
    "shared.block.current_passage": PromptSpec("shared.block.current_passage", frozenset()),
    "shared.block.live_state": PromptSpec("shared.block.live_state", frozenset()),
    "shared.block.task": PromptSpec("shared.block.task", frozenset()),
    "shared.block.instructions": PromptSpec("shared.block.instructions", frozenset()),
    "shared.block.current_text": PromptSpec("shared.block.current_text", frozenset()),
    "shared.block.result_template": PromptSpec("shared.block.result_template", frozenset()),
    "write.system": PromptSpec("write.system", frozenset()),
    "write.instruction_continue": PromptSpec("write.instruction_continue", frozenset()),
    "write.instruction_with_prompt": PromptSpec("write.instruction_with_prompt", frozenset({"prompt"})),
    "edit.system": PromptSpec("edit.system", frozenset()),
    "edit.instruction_template": PromptSpec("edit.instruction_template", frozenset({"prompt", "target"})),
    "design.system": PromptSpec("design.system", frozenset()),
    "design.instruction": PromptSpec("design.instruction", frozenset({"prompt"})),
    "play.system": PromptSpec("play.system", frozenset()),
    "play.instruction_continue": PromptSpec("play.instruction_continue", frozenset()),
    "play.summary_system": PromptSpec("play.summary_system", frozenset()),
    "play.summary_instruction_template": PromptSpec(
        "play.summary_instruction_template", frozenset({"content", "slug"})
    ),
    "advance.system": PromptSpec("advance.system", frozenset()),
    "advance.instruction_template": PromptSpec("advance.instruction_template", frozenset({"days", "current_day", "rolls_text"})),
    "session.summary_system": PromptSpec("session.summary_system", frozenset()),
    "session.summary_instruction_template": PromptSpec("session.summary_instruction_template", frozenset({"content", "slug"})),
    "session.summary_guidance_suffix": PromptSpec(
        "session.summary_guidance_suffix", frozenset({"guidance"})
    ),
    "remember.system": PromptSpec("remember.system", frozenset()),
    "remember.instruction_template": PromptSpec(
        "remember.instruction_template",
        frozenset({"content", "remember_refs", "target_listing"}),
    ),
    "chat.system": PromptSpec("chat.system", frozenset()),
    "chat.with_line_instruction": PromptSpec("chat.with_line_instruction", frozenset({"with_name"})),
    "chat.instruction_continue": PromptSpec("chat.instruction_continue", frozenset({"as_name", "char_content", "with_line"})),
    "chat.instruction_with_directions": PromptSpec(
        "chat.instruction_with_directions",
        frozenset({"as_name", "char_content", "directions", "with_line", "with_name"}),
    ),
    "chat.instruction_with_aside_directions": PromptSpec(
        "chat.instruction_with_aside_directions",
        frozenset({"as_name", "char_content", "directions", "with_name"}),
    ),
    "compress.system": PromptSpec("compress.system", frozenset()),
    "compress.instruction_template": PromptSpec(
        "compress.instruction_template",
        frozenset({"prompt", "node_body"}),
    ),
    "compress.auto_system": PromptSpec("compress.auto_system", frozenset()),
    "compress.auto_directive_low": PromptSpec(
        "compress.auto_directive_low", frozenset({"sm", "m"})
    ),
    "compress.auto_directive_medium": PromptSpec(
        "compress.auto_directive_medium", frozenset({"sm", "m"})
    ),
    "compress.auto_directive_high": PromptSpec("compress.auto_directive_high", frozenset()),
    "compress.auto_instruction_template": PromptSpec(
        "compress.auto_instruction_template",
        frozenset({"node_body", "directive", "sm", "m", "l"}),
    ),
}

_EXTRA_PROMPT_SPECS: dict[str, PromptSpec] = {}


def register_prompt_spec(key: str, variables: frozenset[str] | None = None) -> None:
    """Register a prompt key contributed by a dataset extension."""
    _EXTRA_PROMPT_SPECS[key] = PromptSpec(key, variables or frozenset())


def _all_prompt_specs() -> dict[str, PromptSpec]:
    merged = dict(PROMPT_SPECS)
    merged.update(_EXTRA_PROMPT_SPECS)
    return merged


def prompts_root() -> Path:
    return Path(__file__).parent.parent / "prompts"


def default_prompts_file() -> Path:
    return prompts_root() / "default.toml"


def prompt_pack_file(pack_name: str) -> Path:
    return prompts_root() / "packs" / f"{pack_name}.toml"


def project_prompts_file(project_root: Path) -> Path:
    return project_root / "prompts" / "prompts.toml"


def dataset_prompts_file(dataset_path: Path) -> Path:
    return dataset_path / "prompts" / "prompts.toml"


def load_dataset_prompts_for_project(project_root: Path) -> dict[str, str]:
    """Merge ``prompts/prompts.toml`` from each active dataset (later shadows earlier)."""
    merged: dict[str, str] = {}
    for name in get_selected_datasets(project_root):
        path = resolve_dataset_path(project_root, name)
        if path is None:
            continue
        prompts_path = dataset_prompts_file(path)
        for key, value in _load_prompt_file(prompts_path).items():
            merged[key] = value
    return merged


def get_prompt_text(
    key: str,
    *,
    project_root: Path | None = None,
    dataset_path: Path | None = None,
) -> str:
    """Resolve a prompt for extension registration (project, dataset file, or builtin)."""
    if project_root is not None:
        store = PromptStore(project_root)
        try:
            return store.get(key)
        except ValueError:
            pass
    if dataset_path is not None:
        raw = _load_prompt_file(dataset_prompts_file(dataset_path))
        if key in raw:
            return raw[key]
    builtins = _load_prompt_file(default_prompts_file())
    if key in builtins:
        return builtins[key]
    raise ValueError(f"prompt key has no value: {key}")


def tool_prompt_key(tool_name: str) -> str:
    return f"tool.{tool_name}.prompt_snippet"


def _load_prompt_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    raw_prompts = data.get("prompts")
    if not isinstance(raw_prompts, dict):
        return {}
    raw_map = cast(dict[object, object], raw_prompts)
    result: dict[str, str] = {}

    def _flatten(prefix: str, value: object) -> None:
        if isinstance(value, str):
            result[prefix] = value
            return
        if isinstance(value, dict):
            for child_key, child_value in cast(dict[object, object], value).items():
                if not isinstance(child_key, str):
                    continue
                next_prefix = f"{prefix}.{child_key}" if prefix else child_key
                _flatten(next_prefix, child_value)

    for key, value in raw_map.items():
        if not isinstance(key, str):
            continue
        _flatten(key, value)
    return result


class PromptStore:
    def __init__(self, project_root: Path | None) -> None:
        self._project_root = project_root
        self._builtins = _load_prompt_file(default_prompts_file())
        self._pack_name = get_selected_prompt_pack(project_root) if project_root is not None else None
        self._pack = _load_prompt_file(prompt_pack_file(self._pack_name)) if self._pack_name else {}
        self._project = _load_prompt_file(project_prompts_file(project_root)) if project_root is not None else {}
        self._datasets = (
            load_dataset_prompts_for_project(project_root) if project_root is not None else {}
        )

    def validate_key(self, key: str) -> None:
        specs = _all_prompt_specs()
        if key in specs or key in self._datasets:
            return
        raise ValueError(f"unknown prompt key: {key}")

    def list_keys(self, operator: str | None = None) -> list[str]:
        keys = sorted(set(_all_prompt_specs().keys()) | set(self._datasets.keys()))
        if operator is None:
            return keys
        prefix = f"{operator}."
        return [k for k in keys if k.startswith(prefix)]

    def resolve(self, key: str) -> ResolvedPrompt:
        self.validate_key(key)
        if key in self._project:
            return ResolvedPrompt(key=key, value=self._project[key], source="project")
        if key in self._pack:
            return ResolvedPrompt(key=key, value=self._pack[key], source=f"pack:{self._pack_name}")
        if key in self._datasets:
            return ResolvedPrompt(key=key, value=self._datasets[key], source="dataset")
        if key in self._builtins:
            return ResolvedPrompt(key=key, value=self._builtins[key], source="builtin")
        raise ValueError(f"prompt key has no value: {key}")

    def get(self, key: str) -> str:
        return self.resolve(key).value

    def format(self, key: str, **kwargs: object) -> str:
        spec = _all_prompt_specs().get(key)
        if spec is None:
            raise ValueError(f"unknown prompt key: {key}")
        missing = [var for var in spec.variables if var not in kwargs]
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"missing prompt variables for {key}: {missing_text}")
        return self.get(key).format(**kwargs)

    def set_project_override(self, key: str, value: str) -> None:
        if self._project_root is None:
            raise ValueError("project root is required to set prompt overrides")
        self.validate_key(key)
        path = project_prompts_file(self._project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _load_prompt_file(path)
        current[key] = value
        lines: list[str] = ["[prompts]"]
        for item_key in sorted(current.keys()):
            escaped = current[item_key].replace("'''", "''")
            lines.append(f"{item_key} = '''{escaped}'''")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._project = current

    def clear_project_override(self, key: str) -> None:
        if self._project_root is None:
            raise ValueError("project root is required to clear prompt overrides")
        self.validate_key(key)
        path = project_prompts_file(self._project_root)
        current = _load_prompt_file(path)
        if key not in current:
            return
        current.pop(key, None)
        if not current:
            if path.exists():
                path.unlink()
            self._project = {}
            return
        lines: list[str] = ["[prompts]"]
        for item_key in sorted(current.keys()):
            escaped = current[item_key].replace("'''", "''")
            lines.append(f"{item_key} = '''{escaped}'''")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._project = current
