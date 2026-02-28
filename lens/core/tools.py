"""Tool registry for LLM-callable Lens operators.

Operators register themselves via :func:`register_operator_tool` at module
load time (called by :meth:`~lens.core.operator.ContextAwareOperator.register_as_tool`).
The registry is consulted by :class:`~lens.core.operator.ContextAwareOperator`
to build the tools payload for LLM calls and to dispatch tool-call responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lens.core.project import get_selected_datasets


def operator_applies_to_session(selected: list[str], limited: list[str]) -> bool:
    """Return True if the operator should be available.

    - If limited is empty: operator is always available.
    - If limited is non-empty and selected is empty: operator is excluded.
    - If both are non-empty: operator is available only if they share at least one member.
    """
    if not limited:
        return True
    if not selected:
        return False
    return bool(set(selected) & set(limited))


@dataclass
class OperatorToolDef:
    """Descriptor for an operator exposed as an LLM tool."""

    parameters: dict[str, Any]
    """JSON Schema object describing the operator-specific tool parameters."""

    prompt_snippet: str
    """Appended to the system prompt; also used as the tool description."""

    keep_text: bool
    """Default: write the LLM text to the node before dispatching the tool."""


# Callable type: async (args, session, narrative, depth, on_token, on_confirm) -> None
_TOOL_REGISTRY: dict[str, tuple[OperatorToolDef, Any, list[str]]] = {}


def register_operator_tool(
    name: str,
    tool_def: OperatorToolDef,
    invoke_fn: Any,
    limited_to_datasets: list[str] | None = None,
) -> None:
    """Register an operator as an LLM-callable tool.

    Called at module load time by operator submodules. The registry is keyed
    by operator name. ``invoke_fn`` must be an async callable with signature::

        async (args, session, narrative, depth, on_token, on_confirm) -> None
    """
    _TOOL_REGISTRY[name] = (tool_def, invoke_fn, limited_to_datasets or [])


def get_tool_registry(project_root: Path | None = None) -> dict[str, tuple[OperatorToolDef, Any]]:
    """Return a snapshot of the tool registry, optionally filtered by session datasets.

    When project_root is None, returns all registered tools. When provided, excludes
    operators whose limited_to_datasets (if non-empty) does not intersect with
    get_selected_datasets(project_root).
    """
    if project_root is None:
        return {n: (tdef, fn) for n, (tdef, fn, _) in _TOOL_REGISTRY.items()}
    selected = get_selected_datasets(project_root)
    result: dict[str, tuple[OperatorToolDef, Any]] = {}
    for n, (tdef, fn, limited) in _TOOL_REGISTRY.items():
        if operator_applies_to_session(selected, limited):
            result[n] = (tdef, fn)
    return result
