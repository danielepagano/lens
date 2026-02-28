"""Tool registry for LLM-callable Lens operators.

Operators register themselves via :func:`register_operator_tool` at module
load time (called by :meth:`~lens.core.operator.ContextAwareOperator.register_as_tool`).
The registry is consulted by :class:`~lens.core.operator.ContextAwareOperator`
to build the tools payload for LLM calls and to dispatch tool-call responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
_TOOL_REGISTRY: dict[str, tuple[OperatorToolDef, Any]] = {}


def register_operator_tool(
    name: str,
    tool_def: OperatorToolDef,
    invoke_fn: Any,
) -> None:
    """Register an operator as an LLM-callable tool.

    Called at module load time by operator submodules. The registry is keyed
    by operator name. ``invoke_fn`` must be an async callable with signature::

        async (args, session, narrative, depth, on_token, on_confirm) -> None
    """
    _TOOL_REGISTRY[name] = (tool_def, invoke_fn)


def get_tool_registry() -> dict[str, tuple[OperatorToolDef, Any]]:
    """Return a snapshot of the current tool registry."""
    return dict(_TOOL_REGISTRY)
