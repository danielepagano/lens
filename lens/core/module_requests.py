"""Model-requested modules: a latching command tool that pulls rules into scope.

A **module** is an ordinary KB object a dataset has *registered* as something the
model may pull into scope on its own, mid-scene, with a description of when it is
needed::

    # <dataset>/lens.toml
    [[dataset.modules]]
    id = "rules.combat"
    operators = ["play"]
    description = '''Turn order, actions, and damage resolution.
    Load when violence starts or initiative will be rolled.'''

Why a tool here at all
----------------------
Speed-first operators (``write``, ``play``, ``chat``) deliberately skip command
tools: the assumption is that everything the model needs was funnelled into the
prompt, and a loop that can fire on every beat taxes every beat.  This one is
different in kind.  It is information the fiction structurally points at but the
prompt omits by design, and it is added by **latching**: a module is requested at
most once, and after that it is in scope by ordinary means (an ``include``
annotation, see :mod:`lens.core.mentions`).  The ceiling is N round trips across a
whole session — not N per exchange — and in practice it fires only on a scene
transition nobody prepared for.

The loop
--------
1.  The catalog offers every registered module for the running operator that is
    **not already in scope** — pin, module, include, mention, or ``+`` link
    expansion, all read off :meth:`~lens.core.context.CrawlResult.scoped_kb_ids`
    for the crawl that was just built.  Nothing crawls twice.
2.  The model calls ``load_module`` with **one** id.  Candidate triggers overlap
    heavily (a running fight looks like combat, chase, and exploration at once);
    a single-id signature stops shotgunning and makes a wrong pick cheap.
3.  The handler returns the object's content, so the reply is written with the
    rules in hand, and records the id on a :class:`ModuleRequestSink`.
4.  The operator persists ``[include: <id>]: #`` immediately *before* the block it
    writes (see ``Operator.write_start``).  Above the open tag is the load-bearing
    part: ``write_discard`` truncates from the tag down, so retry and rewind keep
    the include instead of paying for the tool call again.
5.  On later beats the module is in scope, so it is no longer offered.  When every
    module is loaded — or a dataset registered none — there is no tool at all.

There is deliberately no unload tool.  Once the fight ends the include stays, and
the existing structure operators already answer that: ``--end`` the session, or
``collate`` the range into a sub-node, which carries the annotations along with
the prose so the include travels into the child and falls out of the parent's
scope.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from lens.core.knowledge import KnowledgeStore
from lens.core.mentions import INCLUDE, build_mention_annotations
from lens.core.project import get_selected_datasets, resolve_dataset_path
from lens.core.prompts import PromptStore

if TYPE_CHECKING:
    from lens.core.context import CrawlResult
    from lens.core.llm import CommandToolsBundle

LOAD_MODULE_TOOL = "load_module"

UNLOGGED_MODULE_TOOLS = frozenset({LOAD_MODULE_TOOL})
"""Tool calls that are **not** persisted as a ``tool-call`` fence.

A module request already leaves the only record worth keeping — the ``include``
annotation above the block — and the fence would say nothing the cursor does not
already show.  Worse, a persisted fence is part of the assistant turn every later
beat reads back, so it teaches the model a tool name and a fence shape in a
narrative operator that has neither.  Failed calls still land as ``tool-result``
audit fences (see
:func:`~lens.core.generation_artifacts.wrap_command_tool_handlers_for_audit`):
those leave no include, so the trail matters.

The live stream still shows the call — it explains the pause while the model
fetches — it is only the persisted node that stays clean.
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModuleDecl:
    """One registered module: what it is, and which operators may request it."""

    kb_id: str
    description: str
    operators: tuple[str, ...]
    dataset: str


_REGISTRY_CACHE: dict[tuple[Path, tuple[str, ...]], tuple[ModuleDecl, ...]] = {}


def clear_module_registry() -> None:
    """Drop the parsed-declaration cache (tests, and after a lens.toml change)."""
    _REGISTRY_CACHE.clear()


def _parse_dataset_modules(dataset_name: str, dataset_path: Path) -> list[ModuleDecl]:
    """Read ``[[dataset.modules]]`` from one dataset's ``lens.toml``.

    Malformed entries are skipped with a warning rather than raising: a dataset is
    third-party content, and one bad table should not make the project unusable.
    """
    lens_toml = dataset_path / "lens.toml"
    if not lens_toml.is_file():
        return []
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_dataset = config.get("dataset", {})
    if not isinstance(raw_dataset, dict):
        return []
    raw_modules = cast(dict[str, Any], raw_dataset).get("modules")
    if not isinstance(raw_modules, list):
        return []

    decls: list[ModuleDecl] = []
    for raw_entry in cast(list[Any], raw_modules):
        if not isinstance(raw_entry, dict):
            logger.warning("dataset '%s': ignoring non-table module entry", dataset_name)
            continue
        entry = cast(dict[str, Any], raw_entry)
        kb_id = entry.get("id")
        description = entry.get("description")
        raw_operators = entry.get("operators")
        operators = (
            tuple(op for op in cast(list[Any], raw_operators) if isinstance(op, str))
            if isinstance(raw_operators, list)
            else ()
        )
        if not isinstance(kb_id, str) or not kb_id.strip():
            logger.warning("dataset '%s': module entry without an 'id'", dataset_name)
            continue
        if not isinstance(description, str) or not description.strip():
            logger.warning(
                "dataset '%s': module '%s' has no description — the model would have "
                "nothing to decide on, so it is ignored",
                dataset_name,
                kb_id,
            )
            continue
        if not operators:
            logger.warning(
                "dataset '%s': module '%s' targets no operators — ignored",
                dataset_name,
                kb_id,
            )
            continue
        for unsupported in _unsupported_operators(operators):
            logger.warning(
                "dataset '%s': module '%s' targets operator '%s', which does not "
                "accept module requests — that target is inert",
                dataset_name,
                kb_id,
                unsupported,
            )
        decls.append(
            ModuleDecl(
                kb_id=kb_id.strip(),
                description=description.strip(),
                operators=operators,
                dataset=dataset_name,
            )
        )
    return decls


def _unsupported_operators(operators: tuple[str, ...]) -> list[str]:
    """Targets that will never see the tool, for an authoring warning.

    An operator only receives module requests if its generation goes through the
    base inline flow (``Operator.supports_module_requests``).  Unknown names are
    left alone: a dataset may target an operator supplied by another dataset's
    extension that is not loaded in this project.
    """
    from lens.core.operators import get_operator_class_for_name

    unsupported: list[str] = []
    for name in operators:
        op_cls = get_operator_class_for_name(name)
        if op_cls is not None and not op_cls.supports_module_requests:
            unsupported.append(name)
    return unsupported


def dataset_modules(project_root: Path) -> tuple[ModuleDecl, ...]:
    """Every module registered by a dataset active in this project.

    Projects do not get to shadow or add declarations: this is the mechanics you
    opted into by listing the dataset.  Later datasets win on a duplicate id, the
    same way their knowledge shadows earlier ones.
    """
    names = tuple(get_selected_datasets(project_root))
    cache_key = (project_root, names)
    cached = _REGISTRY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    by_id: dict[str, ModuleDecl] = {}
    for dataset_name in names:
        dataset_path = resolve_dataset_path(project_root, dataset_name)
        if dataset_path is None:
            continue
        for decl in _parse_dataset_modules(dataset_name, dataset_path):
            by_id[decl.kb_id.lower()] = decl
    decls = tuple(by_id.values())
    _REGISTRY_CACHE[cache_key] = decls
    return decls


def modules_for_operator(project_root: Path, operator_name: str) -> tuple[ModuleDecl, ...]:
    """Declarations targeting *operator_name*, in declaration order."""
    return tuple(
        decl for decl in dataset_modules(project_root) if operator_name in decl.operators
    )


def unloaded_modules(
    project_root: Path,
    operator_name: str,
    crawl_result: CrawlResult | None,
) -> tuple[ModuleDecl, ...]:
    """Modules worth offering: registered for this operator, not already in scope.

    A module that resolves to no KB object is dropped — a dataset may register an
    id it ships in a later version, and offering a tool that can only fail is
    worse than offering nothing.
    """
    decls = modules_for_operator(project_root, operator_name)
    if not decls:
        return ()
    in_scope: set[str] = (
        crawl_result.scoped_kb_ids() if crawl_result is not None else set()
    )
    kb = KnowledgeStore.for_project(project_root)
    return tuple(
        decl
        for decl in decls
        if decl.kb_id.lower() not in in_scope and kb.exists(decl.kb_id)
    )


def _catalog_text(decls: tuple[ModuleDecl, ...], prompts: PromptStore) -> str:
    return "\n".join(
        prompts.format(
            "shared.module_request_catalog_entry",
            id=decl.kb_id,
            description=decl.description,
        )
        for decl in decls
    )


def module_task_hint(decls: tuple[ModuleDecl, ...], project_root: Path) -> str:
    """Tail appendix for the operator's task listing the modules still available.

    The same ids and descriptions are already in the tool schema; some models read
    the task more reliably than the schema, and the duplication is a few dozen
    bytes at the end of a prompt whose prefix is what gets cached.
    """
    if not decls:
        return ""
    prompts = PromptStore(project_root)
    return prompts.format(
        "shared.module_request_task_hint", catalog=_catalog_text(decls, prompts)
    )


@dataclass(slots=True)
class ModuleRequestSink:
    """Ids the model actually loaded during one generation.

    Written by the handler mid-loop, read by the operator after it, and turned
    into ``include`` annotations at persist time.
    """

    loaded: list[str] = field(default_factory=list[str])

    def holds(self, kb_id: str) -> bool:
        """Whether *kb_id* was already delivered during this generation."""
        return any(existing.lower() == kb_id.lower() for existing in self.loaded)

    def record(self, kb_id: str) -> None:
        """Latch *kb_id*: it will be written as an ``include`` at persist time."""
        if not self.holds(kb_id):
            self.loaded.append(kb_id)

    def include_annotations(self) -> str:
        """The ``[include: id]: #`` block to persist before the generated one."""
        return build_mention_annotations(INCLUDE, self.loaded)


def build_module_request_bundle(
    decls: tuple[ModuleDecl, ...],
    sink: ModuleRequestSink,
    project_root: Path,
) -> CommandToolsBundle | None:
    """The ``load_module`` tool for *decls*, or ``None`` when there is nothing to offer."""
    if not decls:
        return None
    from lens.core.llm import CommandToolsBundle

    prompts = PromptStore(project_root)
    allowed = {decl.kb_id.lower(): decl for decl in decls}
    ids = [decl.kb_id for decl in decls]

    async def _load_module(args: dict[str, Any], root: Path) -> str:
        raw = args.get("module") or args.get("id")
        if not isinstance(raw, str) or not raw.strip():
            return f"(error: 'module' is required — one of: {', '.join(ids)})"
        requested = raw.strip()
        decl = allowed.get(requested.lower())
        if decl is None:
            return (
                f"(error: {requested!r} is not an available module — "
                f"one of: {', '.join(ids)})"
            )
        suffix = prompts.format("shared.module_request_loaded_suffix", id=decl.kb_id)
        if sink.holds(decl.kb_id):
            return f"(already loaded){suffix}"
        from lens.core.command_tools import format_objects_for_model

        objects = KnowledgeStore.for_project(root).get_objects([decl.kb_id])
        formatted = format_objects_for_model(objects)
        if not formatted:
            # Latch only on a real delivery.  Recording first would write an
            # include for a module the model never received — scope the reader
            # can see and the model cannot.
            return f"(error: module {decl.kb_id} is registered but has no KB object)"
        sink.record(decl.kb_id)
        return f"{formatted}{suffix}"

    tool_spec: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": LOAD_MODULE_TOOL,
            "description": prompts.format(
                "shared.module_request_tool_description",
                catalog=_catalog_text(decls, prompts),
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": ids,
                        "description": "Exactly one module id from the list above.",
                    },
                },
                "required": ["module"],
            },
        },
    }
    return CommandToolsBundle(tools=[tool_spec], handlers={LOAD_MODULE_TOOL: _load_module})
