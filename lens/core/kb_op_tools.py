"""The four KB verbs, as tools that propose instead of write.

An agent should never need a fenced ``kb`` block again, and partial coverage
would mean it still does — so the surface is all four verbs or none:

============  ==========================================================
``kb_add``    whole body; the one case whole-body emission is right for
``kb_patch``  anchored find/replace, the existing ``text_select.Patch``
``kb_tag``    add and remove tags, both directions
``kb_remove`` the verb that existed in neither channel
============  ==========================================================

All four are tool calls and none of them has a fenced form, for one reason:
**validation happens against the overlay at call time**, and a tool call is the
only emit form with a return channel inside the turn.  A call that does not
validate writes no proposal, returns its error, and the model tries again —
which is the entire failure story, replacing "the whole batch errors into a log
nobody is reading at ``--end``".

Nothing here touches ``knowledge/``.  Each successful call records a
:class:`~lens.core.kb_pending.KbOp` into the generation's sink, which is both
what makes it visible to the *next* call in the same turn and what gets
persisted as a ``[kb-op …]: #`` block inside the operator's block.

The refusals are the guardrails, and they are deliberately asymmetric with the
fold.  ``kb_add`` refuses an id that already resolves on disk, because a
whole-body write over an existing object is a silent clobber with no diff — the
exact thing this system exists to stop — while the *fold* still applies such an
op, because a person who hand-writes one has said what they mean.  The tool is
the guardrail; the fold is the machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from lens.core.command_tools import (
    KB_PATCH_TOOL,
    encode_patch_contents,
    format_objects_for_model,
)
from lens.core.kb_pending import KbOp, KbOpSink
from lens.core.knowledge import KnowledgeStore, is_valid_tag, parse_id
from lens.core.text_select import SelectionError, apply_kb_patches

if TYPE_CHECKING:
    from lens.core.llm import CommandToolsBundle

KB_ADD_TOOL = "kb_add"
KB_PATCH_PROPOSAL_TOOL = "kb_patch"
KB_TAG_TOOL = "kb_tag"
KB_REMOVE_TOOL = "kb_remove"

KB_OP_TOOLS = frozenset(
    {KB_ADD_TOOL, KB_PATCH_PROPOSAL_TOOL, KB_TAG_TOOL, KB_REMOVE_TOOL}
)
"""Tool names whose persisted record is the ``[kb-op]`` block, not a fence.

Passed as ``unlogged_tool_names`` so the default ``tool-call`` fence is
suppressed.  Without that, each proposal's full body would be persisted twice —
once in the block, and once in a fence that sits in the assistant turn every
later beat reads back, which is one of the four problems this replaces.
"""

_NOT_WRITTEN = "Nothing is written until the session closes."


def _bad_id(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return "(error: 'id' is required)"
    try:
        _, key = parse_id(raw.strip())
    except ValueError as e:
        return f"(error: {e})"
    if key == "_template":
        return (
            "(error: templates are not objects; edit one with "
            "'lens kb template', not a KB verb)"
        )
    return None


def _canonical(raw: str) -> str:
    type_name, key = parse_id(raw.strip())
    return f"{type_name}.{key}"


def build_kb_op_bundle(sink: KbOpSink, project_root: Path) -> CommandToolsBundle:
    """The four verbs, recording into *sink*.

    Built as a closure over the sink rather than registered globally, exactly
    like :func:`~lens.core.module_requests.build_module_request_bundle`: the
    verbs only mean anything inside a generation that has somewhere to put the
    proposals.
    """
    from lens.core.llm import CommandToolsBundle

    def _store() -> KnowledgeStore:
        return KnowledgeStore.for_project(project_root)

    async def _kb_add(args: dict[str, Any], root: Path) -> str:
        del root
        raw_id = args.get("id")
        bad = _bad_id(raw_id)
        if bad:
            return bad
        canonical = _canonical(cast(str, raw_id))
        body = args.get("body")
        if not isinstance(body, str):
            return "(error: 'body' is required and must be a string)"
        kb = _store()
        layer = kb.pending_layer()
        if canonical not in layer.objects and kb.exists(canonical):
            source = kb.describe_source(canonical)
            where = source.label if source is not None else "this project"
            return (
                f"(error: {canonical} already exists ({where}). kb_add replaces a "
                "whole body with no diff — use kb_patch to change it, or "
                "kb_remove first if you really mean to start over.)"
            )
        from lens.core.annotations import encode_ai_secrets_for_persist

        sink.record(
            KbOp(op="add", id=canonical, body=encode_ai_secrets_for_persist(body))
        )
        verb = "replacing your earlier proposal for" if canonical in layer.objects else "created"
        return f"OK: {verb} {canonical}. {_NOT_WRITTEN}"

    async def _kb_patch(args: dict[str, Any], root: Path) -> str:
        del root
        raw_id = args.get("id")
        bad = _bad_id(raw_id)
        if bad:
            return bad
        canonical = _canonical(cast(str, raw_id))
        patches = args.get("patches")
        if not isinstance(patches, list) or not patches:
            return "(error: 'patches' must be a non-empty array)"
        kb = _store()
        existing = kb.get_objects([canonical]).get(canonical)
        if existing is None:
            return (
                f"(error: {canonical} does not exist, so there is nothing to "
                "patch. Use kb_add to create it.)"
            )
        encoded = encode_patch_contents(cast(list[dict[str, Any]], patches))
        # Resolve now, against the overlay, so a patch that cannot land never
        # becomes a proposal — the model gets the failure in-loop instead of at
        # session close.
        try:
            _new_text, kind = apply_kb_patches(
                existing.text, encoded, source_id=f"kb-op:{canonical}"
            )
        except SelectionError as e:
            return f"(error: {e})"
        if kind == "already_present":
            return f"OK: already present for {canonical}"
        if kind == "no_changes":
            return f"OK: no changes for {canonical}"
        sink.record(KbOp(op="patch", id=canonical, patches=tuple(encoded)))
        updated = kb.get_objects([canonical]).get(canonical)
        body = format_objects_for_model({canonical: updated}) if updated else ""
        return f"OK: patched {canonical}. {_NOT_WRITTEN}\n\n{body}".rstrip()

    async def _kb_tag(args: dict[str, Any], root: Path) -> str:
        del root
        raw_id = args.get("id")
        bad = _bad_id(raw_id)
        if bad:
            return bad
        canonical = _canonical(cast(str, raw_id))
        tags = _string_list(args.get("tags"))
        remove_tags = _string_list(args.get("remove_tags"))
        if not tags and not remove_tags:
            return "(error: give at least one of 'tags' or 'remove_tags')"
        malformed = [t for t in (*tags, *remove_tags) if not is_valid_tag(t)]
        if malformed:
            return (
                f"(error: malformed tags {', '.join(repr(t) for t in malformed)} — "
                "a tag is a bare token, 'namespace:value', or 'type.key' to link "
                "another object, never both a colon and a dot)"
            )
        kb = _store()
        if not kb.exists(canonical):
            return f"(error: {canonical} does not exist, so there is nothing to tag)"
        dangling = kb.get_invalid_dot_tags(tags)
        if dangling:
            return (
                f"(error: {', '.join(dangling)} point at objects that do not "
                "exist. Create them first, or drop the link.)"
            )
        sink.record(
            KbOp(
                op="tag",
                id=canonical,
                tags=tuple(tags),
                remove_tags=tuple(remove_tags),
            )
        )
        parts: list[str] = []
        if tags:
            parts.append(f"+{', +'.join(tags)}")
        if remove_tags:
            parts.append(f"-{', -'.join(remove_tags)}")
        return f"OK: {canonical} {' '.join(parts)}. {_NOT_WRITTEN}"

    async def _kb_remove(args: dict[str, Any], root: Path) -> str:
        del root
        raw_id = args.get("id")
        bad = _bad_id(raw_id)
        if bad:
            return bad
        canonical = _canonical(cast(str, raw_id))
        kb = _store()
        layer = kb.pending_layer()
        if canonical in layer.objects and canonical in layer.created:
            sink.record(KbOp(op="remove", id=canonical))
            return f"OK: dropped your proposed {canonical}. Nothing was ever written."
        if not kb.exists(canonical):
            return f"(error: {canonical} does not exist, so there is nothing to remove)"
        source = kb.describe_source(canonical)
        base = source.base if source is not None and source.kind == "pending" else source
        if base is not None and base.kind == "dataset":
            return (
                f"(error: {canonical} resolves from dataset:{base.dataset}. "
                "Datasets are read-only and nothing in this session created it, "
                "so there is nothing here to remove.)"
            )
        sink.record(KbOp(op="remove", id=canonical))
        shadowed = base.shadows if base is not None else ()
        if shadowed:
            return (
                f"OK: removing the project copy of {canonical} — "
                f"dataset:{shadowed[0]} will resolve again. {_NOT_WRITTEN}"
            )
        return f"OK: removing {canonical}. {_NOT_WRITTEN}"

    tools: list[dict[str, Any]] = [
        _tool_spec(
            KB_ADD_TOOL,
            "Create a new KB object with a whole body. Refuses an id that "
            "already exists — use kb_patch for those. The object is visible to "
            "every later lookup in this session but is not written to disk "
            "until the session closes.",
            {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Canonical id, 'type.key' (e.g. 'loc.vault').",
                    },
                    "body": {
                        "type": "string",
                        "description": (
                            "The object's full markdown body. Follow "
                            "'type._template' when one exists. The first three "
                            "lines are read as the object's self-description, so "
                            "open with what it is and when it applies."
                        ),
                    },
                },
                "required": ["id", "body"],
            },
        ),
        _tool_spec(
            KB_PATCH_PROPOSAL_TOOL,
            KB_PATCH_TOOL.description
            + " The change is proposed, not written: it is visible to every "
            "later lookup in this session and reaches disk when the session "
            "closes.",
            KB_PATCH_TOOL.parameters,
        ),
        _tool_spec(
            KB_TAG_TOOL,
            "Add or remove tags on a KB object. A tag is a bare token, "
            "'namespace:value', or 'type.key' to link another object — a link "
            "is what makes '<id>+' pull that object into scope.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Canonical KB id."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to add.",
                    },
                    "remove_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to remove.",
                    },
                },
                "required": ["id"],
            },
        ),
        _tool_spec(
            KB_REMOVE_TOOL,
            "Remove a KB object. Use it to take back something you created "
            "earlier in this session, or to delete a project object that should "
            "not exist. Objects that live only in a dataset cannot be removed.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Canonical KB id."},
                },
                "required": ["id"],
            },
        ),
    ]
    handlers = {
        KB_ADD_TOOL: _kb_add,
        KB_PATCH_PROPOSAL_TOOL: _kb_patch,
        KB_TAG_TOOL: _kb_tag,
        KB_REMOVE_TOOL: _kb_remove,
    }
    return CommandToolsBundle(tools=tools, handlers=cast(Any, handlers))


def _tool_spec(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    return [str(v).strip() for v in items if isinstance(v, str) and str(v).strip()]


def render_kb_op_persist(name: str, args: dict[str, Any], result: str) -> str | None:
    """The ``[kb-op …]: #`` block to persist for one call, or ``""`` for none.

    A pure function of the call arguments, gated on the result: a failed call
    leaves no proposal, so it renders nothing (the audit ``tool-result`` fence
    still lands, which is the right asymmetry — a failure has no block behind
    it).  Deriving the block from the arguments rather than from the sink keeps
    persistence stateless and keeps the two from ever disagreeing about what was
    proposed.
    """
    if name not in KB_OP_TOOLS:
        return None
    if not result.startswith("OK:"):
        return ""
    op = _op_from_args(name, args)
    if op is None:
        return ""
    if name == KB_PATCH_PROPOSAL_TOOL and (
        "no changes for" in result or "already present for" in result
    ):
        return ""
    from lens.core.kb_pending import render_kb_op

    return render_kb_op(op)


def _op_from_args(name: str, args: dict[str, Any]) -> KbOp | None:
    raw_id = args.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    try:
        canonical = _canonical(raw_id)
    except ValueError:
        return None
    if name == KB_ADD_TOOL:
        body = args.get("body")
        if not isinstance(body, str):
            return None
        from lens.core.annotations import encode_ai_secrets_for_persist

        return KbOp(op="add", id=canonical, body=encode_ai_secrets_for_persist(body))
    if name == KB_PATCH_PROPOSAL_TOOL:
        patches = args.get("patches")
        if not isinstance(patches, list) or not patches:
            return None
        encoded = encode_patch_contents(cast(list[dict[str, Any]], patches))
        return KbOp(op="patch", id=canonical, patches=tuple(encoded))
    if name == KB_TAG_TOOL:
        return KbOp(
            op="tag",
            id=canonical,
            tags=tuple(_string_list(args.get("tags"))),
            remove_tags=tuple(_string_list(args.get("remove_tags"))),
        )
    if name == KB_REMOVE_TOOL:
        return KbOp(op="remove", id=canonical)
    return None
