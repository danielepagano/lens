"""Reusable transforms for crawl graphs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from lens.core.address import NarrativeAddress
from lens.core.annotations import decode_ai_secrets
from lens.core.crawl_graph import (
    ComponentSource,
    CrawlComponent,
    CrawlGraph,
    ExpansionPolicy,
    RenderEffect,
    kb_ids_from_effects,
)
from lens.core.dice import DiceError, substitute_rolls
from lens.core.knowledge import KnowledgeObject, KnowledgeStore
from lens.core.mount_embed_strip import strip_standalone_lens_mount_attachment_lines
from lens.core.now import substitute_now
from lens.core.project import resolve_address
from lens.core.storage import Storage

_MENTION_END = r"(?=[\s\.,;:!\?\)]|$)"
AT_KB_RE = re.compile(
    r"@([a-zA-Z0-9_-]+\.[a-zA-Z0-9_.-]*[a-zA-Z0-9_-])" + _MENTION_END
)
"""The one `@type.key` pattern.

Shared with :meth:`~lens.core.operator.Operator.mention_pins` so a token that
resolves in prose also resolves when a command turns it into an annotation.
Sentence punctuation ends a mention — ``I cast @spell.aid on @pc.rowan, then…``
names two objects, and nobody should have to leave a space before the comma.
"""
_AT_NODE_SLICE_RE = re.compile(
    r"@((?:/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*|[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*)@[0-9]+:[0-9]+)"
    + _MENTION_END
)
_AT_VAR_RE = re.compile(r"@var:([a-zA-Z0-9_-]+)" + _MENTION_END)
_AT_ROLL_RE = re.compile(r"@roll\s+\(([^)]+)\)|@roll\s+(\S+)")
_AT_NOW_RE = re.compile(r"@now")


def expansion_policy_from_tags(tags: Iterable[str]) -> ExpansionPolicy:
    """Derive expansion policy from KB object tags."""
    if "inline" in tags:
        return ExpansionPolicy(mode="inline")
    return ExpansionPolicy(mode="reference")


STATE_TAG = "state"
"""Reserved tag marking a KB object the user intends to update as the session runs.

State objects render at the **tail** of the prompt — after the last transcript
turn, immediately before ``[TASK]`` — instead of inside ``[RELEVANT KNOWLEDGE]``.
A mutable object sitting in the cacheable prefix invalidates the whole prompt
every time it changes; at the tail it costs only its own tokens, and it lands
next to the task where it is most decision-relevant.
"""


def is_state_tags(tags: Iterable[str]) -> bool:
    """Whether *tags* mark the object as live state (see :data:`STATE_TAG`)."""
    return STATE_TAG in tags


def substitute_vars(text: str, vars: dict[str, str]) -> str:
    """Replace ``@var:slug`` tokens with values from *vars*."""
    if not vars or "@var:" not in text:
        return text

    def repl(match: re.Match[str]) -> str:
        slug = match.group(1)
        return vars.get(slug, match.group(0))

    return _AT_VAR_RE.sub(repl, text)


def substitute_inline_kb(
    text: str,
    *,
    project_root: Path,
    storage: Storage,
    max_depth: int = 8,
) -> str:
    """Replace ``@kb.id`` mentions whose KB has the ``inline`` tag with the object body.

    Recursively expands inline references within resolved bodies up to *max_depth*,
    with cycle detection.
    """
    kb = KnowledgeStore.for_project(project_root)
    seen: set[str] = set()

    def _resolve(s: str, depth: int) -> str:
        if depth > max_depth or "@" not in s:
            return s

        def repl(match: re.Match[str]) -> str:
            raw_id = match.group(1)
            objects = kb.get_objects([raw_id])
            obj = objects.get(raw_id.lower()) or objects.get(raw_id)
            if obj is None or expansion_policy_from_tags(obj.tags).mode != "inline":
                return match.group(0)
            if obj.id in seen:
                return match.group(0)
            seen.add(obj.id)
            body = storage.normalize_raw_text(
                obj.text, source_id=f"inline:{obj.id}"
            ).strip_comments_text.strip()
            return _resolve(body, depth + 1)

        return AT_KB_RE.sub(repl, s)

    return _resolve(text, 0)


class SecretDecodeTransform:
    """Turn stored ``ai:secret`` blocks into the model form, exactly once.

    :func:`~lens.core.annotations.decode_ai_secrets` is ROT13, an involution, so
    a second pass over the same component *re-encodes* it and the model is shown
    ciphertext.  It then copies that ciphertext back verbatim, persist encodes it
    once more, and the plaintext lands on disk — issue #74.  A graph does get
    transformed twice in the normal flow (``crawl`` builds it, then
    ``_prepare_render_graph`` re-runs the defaults over the render-time
    components it just added), so ``transform_history`` is the guard: components
    already decoded are skipped, newly added ones still get their single pass.
    """

    name = "secret-decode"

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        for component in graph.components:
            if self.name in component.transform_history:
                continue
            decoded = decode_ai_secrets(component.text)
            if decoded != component.text:
                component.text = decoded
                component.transform_history.append(self.name)
        return graph


class StripStandaloneMountEmbedsTransform:
    name = "strip-mount-embeds"

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        for component in graph.components:
            if "llm" not in component.visibility:
                continue
            stripped = strip_standalone_lens_mount_attachment_lines(component.text)
            if stripped != component.text:
                component.text = stripped
                component.transform_history.append(self.name)
        return graph


class AtExpansionTransform:
    """Resolve supported `@` expressions across every LLM-visible text component.

    With ``force_inline_kb=True``, every ``@kb.id`` mention is replaced by the object
    body (same as the ``inline`` tag policy). Use this for flat prompt consumers
    (:class:`~lens.core.prompt_transforms.PromptTransformTarget.FLAT`) that do not run
    ``crawl()`` / crawl-assembled context blocks.
    """

    name = "at-expansion"

    def __init__(
        self,
        *,
        project_root: Path,
        storage: Storage,
        max_depth: int = 8,
        sticky_components: set[str] | None = None,
        force_inline_kb: bool = False,
    ) -> None:
        self._project_root = project_root
        self._storage = storage
        self._kb = KnowledgeStore.for_project(project_root)
        self._max_depth = max(1, max_depth)
        self._sticky_components = sticky_components or set()
        self._force_inline_kb = force_inline_kb

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        depth = 0
        seen_inline: set[str] = set()
        max_depth_hit = True
        while depth < self._max_depth:
            changed = False
            snapshot = list(graph.components)
            for component in snapshot:
                if "llm" not in component.visibility and "hidden" not in component.visibility:
                    continue
                before = component.text
                component.text = self._expand_vars(component.text, graph, component)
                component.text = self._expand_rolls(component.text, graph, component)
                component.text = self._expand_now(component.text, graph, component)
                component.text = self._expand_kb_mentions(
                    component.text, graph, component, seen_inline
                )
                component.text = self._expand_node_slices(component.text, graph, component)
                if component.text != before:
                    changed = True
                    component.transform_history.append(self.name)
            if not changed:
                max_depth_hit = False
                break
            depth += 1

        unresolved = self._collect_unresolved_tokens(graph)
        if not unresolved and not max_depth_hit:
            return graph
        detail = (
            f"; unresolved tokens: {sorted(unresolved)}" if unresolved else ""
        )
        if max_depth_hit:
            text = f"@ expansion stopped after {self._max_depth} passes{detail}"
        else:
            text = f"@ expansion left unresolved tokens{detail}"
        # The graph is transformed twice in the normal flow — once by `crawl`,
        # once by `_prepare_render_graph` — so without this the same warning is
        # reported as two components.
        if any(c.kind == "warning" and c.text == text for c in graph.components):
            return graph
        graph.add_component(
            CrawlComponent(
                id=graph.next_id("warning"),
                kind="warning",
                text=text,
                role="log",
                source=ComponentSource(kind="transform", identifier=self.name),
                visibility={"log"},
            )
        )
        return graph

    def _collect_unresolved_tokens(self, graph: CrawlGraph) -> set[str]:
        """Tokens that were *meant* to expand and did not.

        A plain ``@type.key`` is deliberately inert — it is a shortcut that
        wrote a mention annotation, and the annotation is what adds scope, so
        finding one left in the prose is the normal case and warning about it
        is pure noise.  Only an ``inline``-tagged object is obliged to expand
        here, so only a surviving one of those is a real failure.
        """
        unresolved: set[str] = set()
        for component in graph.components:
            if "llm" not in component.visibility and "hidden" not in component.visibility:
                continue
            for m in _AT_VAR_RE.finditer(component.text):
                unresolved.add(m.group(0))
            for m in AT_KB_RE.finditer(component.text):
                if self._is_inline_kb(m.group(1)):
                    unresolved.add(m.group(0))
            for m in _AT_NODE_SLICE_RE.finditer(component.text):
                unresolved.add(m.group(0))
            for m in _AT_NOW_RE.finditer(component.text):
                unresolved.add(m.group(0))
            for m in _AT_ROLL_RE.finditer(component.text):
                unresolved.add(m.group(0))
        return unresolved

    def _is_inline_kb(self, raw_id: str) -> bool:
        objects = self._kb.get_objects([raw_id])
        obj = objects.get(raw_id.lower()) or objects.get(raw_id)
        return obj is not None and expansion_policy_from_tags(obj.tags).mode == "inline"

    def _expand_vars(
        self, text: str, graph: CrawlGraph, component: CrawlComponent
    ) -> str:
        if not graph.vars or "@var:" not in text:
            return text
        before = text
        result = substitute_vars(text, graph.vars)
        if result == before:
            return result
        for match in _AT_VAR_RE.finditer(before):
            slug = match.group(1)
            value = graph.vars.get(slug)
            if value is None:
                continue
            graph.add_effect(
                RenderEffect(
                    kind="var",
                    token=match.group(0),
                    result=value,
                    source_component_id=component.id,
                )
            )
        return result

    def _expand_rolls(
        self, text: str, graph: CrawlGraph, component: CrawlComponent
    ) -> str:
        if "@roll" not in text:
            return text

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            try:
                result = substitute_rolls(token)
            except DiceError:
                return token
            graph.add_effect(
                RenderEffect(
                    kind="roll",
                    token=token,
                    result=result,
                    source_component_id=component.id,
                    sticky=component.id in self._sticky_components,
                )
            )
            return result

        return _AT_ROLL_RE.sub(repl, text)

    def _expand_now(
        self, text: str, graph: CrawlGraph, component: CrawlComponent
    ) -> str:
        if "@now" not in text:
            return text
        result = substitute_now(text)
        if result != text:
            graph.add_effect(
                RenderEffect(
                    kind="now",
                    token="@now",
                    result=result,
                    source_component_id=component.id,
                )
            )
        return result

    def _expand_kb_mentions(
        self,
        text: str,
        graph: CrawlGraph,
        component: CrawlComponent,
        seen_inline: set[str],
    ) -> str:
        """Substitute `inline`-tagged KB bodies; leave every other `@` alone.

        A reference-mode ``@type.key`` used to inject a ``mention-kb:`` component
        into ``[RELEVANT KNOWLEDGE]`` from wherever it was found — including
        ancestor prose pulled in by the spine crawl, which is why a mention from
        round 1 never went away.  Scope is now added by the annotation a command
        writes (:mod:`lens.core.mentions`), which expands at its own line, so the
        ``@`` left in the prose is inert: a shortcut that wrote the annotation,
        nothing more, exactly like ``@roll``.
        """

        def repl(match: re.Match[str]) -> str:
            raw_id = match.group(1)
            objects = self._kb.get_objects([raw_id])
            obj = objects.get(raw_id.lower()) or objects.get(raw_id)
            if obj is None:
                return match.group(0)
            policy = expansion_policy_from_tags(obj.tags)
            if policy.mode != "inline" and not self._force_inline_kb:
                return match.group(0)
            if obj.id in seen_inline:
                return match.group(0)
            seen_inline.add(obj.id)
            body = self._storage.normalize_raw_text(
                obj.text, source_id=f"inline:{obj.id}"
            ).strip_comments_text.strip()
            graph.add_effect(
                RenderEffect(
                    kind="kb-inline",
                    token=match.group(0),
                    result=obj.id,
                    source_component_id=component.id,
                )
            )
            return body

        return AT_KB_RE.sub(repl, text)

    def _expand_node_slices(
        self, text: str, graph: CrawlGraph, component: CrawlComponent
    ) -> str:
        for match in _AT_NODE_SLICE_RE.finditer(text):
            raw = match.group(1)
            formatted = self._format_node_slice_ref(raw)
            if formatted is None:
                continue
            component_id = f"mention-ref:{raw}"
            if graph.component_by_id(component_id) is None:
                graph.add_component(
                    CrawlComponent(
                        id=component_id,
                        kind="reference",
                        text=formatted,
                        source=ComponentSource(
                            kind="narrative",
                            identifier=raw,
                            metadata={"expanded_from": component.id},
                        ),
                        priority=len(graph.components),
                        metadata={"expanded_from": component.id},
                    )
                )
                graph.add_effect(
                    RenderEffect(
                        kind="node-slice-reference",
                        token=match.group(0),
                        result=raw,
                        source_component_id=component.id,
                    )
                )
        return text

    def _format_node_slice_ref(self, raw: str) -> str | None:
        try:
            addr = NarrativeAddress.parse(raw)
        except ValueError:
            return None
        if addr.cursor or addr.line is None or addr.line_end is None:
            return None
        if addr.line < 1 or addr.line_end < addr.line:
            return None
        try:
            resolved = resolve_address(addr, self._project_root)
        except ValueError:
            return None
        if (
            resolved.cursor
            or resolved.narrative is None
            or resolved.line is None
            or resolved.line_end is None
        ):
            return None
        node = resolved.to_node(self._project_root)
        if not node.exists():
            return None
        lines = node.md_path().read_text(encoding="utf-8").split("\n")
        if resolved.line_end > len(lines):
            return None
        excerpt = "\n".join(lines[resolved.line - 1 : resolved.line_end]).rstrip()
        if not excerpt:
            return None
        return f"REF[{str(resolved)!r}]\n{excerpt}\n"


class RulesCompanionTransform:
    """Add `rules.<type>` KB companions for every non-rules object in scope.

    ``<type>._template`` tells ``design`` how to *create* an object of a type;
    ``rules.<type>`` tells ``play`` how to *use* one.  Ship the file and it
    activates — no tagging, nothing for an author to remember — which is the
    whole point: per-type running guidance lives once here instead of being
    restated in every object of that type.

    "In scope" has to mean every route, not just pins.  An object reaches the
    model as a front-matter pin, as a ``+`` link off one, as a session module,
    or as an ``@`` mention / ``include`` that splices it into the prose.  The
    last group leaves a render effect rather than a pin, so reading
    ``pinned_ids`` alone silently dropped the companion exactly when the player
    reached for something mid-scene — ``@stat.wolf`` in an unprepared fight put
    a stat block in front of a model that had never been told how to run one.
    """

    name = "rules-companion"

    def __init__(self, *, project_root: Path, storage: Storage) -> None:
        self._project_root = project_root
        self._storage = storage
        self._kb = KnowledgeStore.for_project(project_root)

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        scoped_ids = [
            *graph.pinned_ids,
            *kb_ids_from_effects(graph.effects),
        ]
        scoped_set = {kb_id.rstrip("+").lower() for kb_id in scoped_ids}
        types_seen: set[str] = set()
        for kb_id in scoped_ids:
            base = kb_id.rstrip("+")
            if "." not in base:
                continue
            obj_type = base.split(".", 1)[0].lower()
            if obj_type != "rules":
                types_seen.add(obj_type)

        companion_ids: list[str] = []
        for obj_type in sorted(types_seen):
            rules_id = f"rules.{obj_type}"
            if rules_id.lower() not in scoped_set and self._kb.exists(rules_id):
                companion_ids.append(rules_id)

        if not companion_ids:
            return graph

        objects = self._kb.get_objects(companion_ids)
        for companion_id in companion_ids:
            obj = objects.get(companion_id)
            if obj is None:
                continue
            if graph.component_by_id(f"rules-companion:{obj.id}") is not None:
                continue
            formatted_obj = cast(
                object,
                self._storage.format_kb_prompt_block(
                    canonical_id=obj.id,
                    text=obj.text,
                    tags=obj.tags,
                    include_comments=False,
                    source_id=f"rules-companion:{obj.id}",
                ),
            )
            formatted = (
                formatted_obj
                if isinstance(formatted_obj, str)
                else obj.format(include_comments=False)
            )
            graph.add_component(
                CrawlComponent(
                    id=f"rules-companion:{obj.id}",
                    kind="knowledge",
                    text=formatted,
                    source=ComponentSource(
                        kind="transform",
                        identifier=self.name,
                        metadata={"kb_id": obj.id},
                    ),
                    priority=len(graph.components),
                    metadata={
                        "kb_id": obj.id,
                        "tags": ",".join(obj.tags),
                        "expansion_policy": "reference",
                    },
                )
            )
            graph.pinned_ids.append(obj.id)
            graph.add_effect(
                RenderEffect(
                    kind="rules-companion",
                    token=obj.id,
                    result=obj.id,
                    source_component_id=f"rules-companion:{obj.id}",
                )
            )
        return graph


class ModuleTransform:
    """Resolve session *modules* into knowledge components.

    A *module* is a KB id (e.g. ``design.encounter``) that drives a session's
    behaviour.  This transform looks up each module id, formats it as a
    knowledge block, and adds it to the graph with ``module`` provenance.  It
    also tries to resolve a sibling ``<key>._template`` companion (where
    ``<key>`` is the part after the last ``.`` in the module id) and includes
    it when present.

    **Modules always resolve with ``+``.**  A module's dot-tags pointing at
    other KB objects (``rules.system`` on ``design.encounter``, say) are
    resolved one hop and added alongside it.  That is what lets a dataset
    attach its rules to a module declaratively, instead of hoping the model
    calls ``kb_get`` for them mid-session.

    Already-pinned modules and templates are skipped — the transform is a
    no-op for ids resolved through normal ``kb_pin`` front-matter chains.

    With *expand_facets* (set by the prep-side operators, never by ``play``) a
    module id also pulls its ``-`` facets, exactly as an ancestor ``kb_pin``
    does: ``--module`` names an id directly, so it is a root pin and the
    root-pins-only rule includes it.  Facets are taken off the module id
    itself, never off the objects its ``+`` links reach.
    """

    name = "module"

    def __init__(
        self,
        *,
        module_ids: Iterable[str],
        project_root: Path,
        storage: Storage,
        expand_facets: bool = False,
    ) -> None:
        self._module_ids = [m for m in module_ids if m]
        self._project_root = project_root
        self._storage = storage
        self._expand_facets = expand_facets
        self._kb = KnowledgeStore.for_project(project_root)

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        for module_id in self._module_ids:
            self._add_module_component(graph, module_id, role="module")
            if self._expand_facets:
                for facet_id in self._kb.list_facet_ids(module_id):
                    self._add_module_component(
                        graph, facet_id, role="module-facet", facet_of=module_id
                    )
            template_id = _template_companion_id(module_id)
            if template_id:
                self._add_module_component(graph, template_id, role="template")
        return graph

    def _add_module_component(
        self, graph: CrawlGraph, kb_id: str, *, role: str, facet_of: str | None = None
    ) -> None:
        if kb_id in graph.pinned_ids:
            return
        if graph.component_by_id(f"module:{kb_id}") is not None:
            return
        # `+`: the module itself, then whatever its dot-tags link to.
        ordered_ids, objects = self._kb.get_objects_with_links([f"{kb_id}+"])
        for resolved_id in ordered_ids:
            obj = objects.get(resolved_id)
            if obj is None:
                continue
            if obj.id == kb_id:
                self._add_component(
                    graph, obj, role=role, linked_from=None, facet_of=facet_of
                )
            else:
                self._add_component(graph, obj, role=f"{role}-link", linked_from=kb_id)

    def _add_component(
        self,
        graph: CrawlGraph,
        obj: KnowledgeObject,
        *,
        role: str,
        linked_from: str | None,
        facet_of: str | None = None,
    ) -> None:
        if obj.id in graph.pinned_ids:
            return
        component_id = f"module:{obj.id}"
        if graph.component_by_id(component_id) is not None:
            return
        formatted = self._storage.format_kb_prompt_block(
            canonical_id=obj.id,
            text=obj.text,
            tags=obj.tags,
            include_comments=False,
            source_id=f"module:{obj.id}",
        )
        graph.add_component(
            CrawlComponent(
                id=component_id,
                kind="knowledge",
                text=formatted,
                source=ComponentSource(
                    kind="transform",
                    identifier=self.name,
                    metadata={"kb_id": obj.id, "module_role": role},
                ),
                priority=len(graph.components),
                metadata={
                    "kb_id": obj.id,
                    "tags": ",".join(obj.tags),
                    "module_role": role,
                    **({"module_linked_from": linked_from} if linked_from else {}),
                    **({"facet_of": facet_of} if facet_of else {}),
                    "expansion_policy": expansion_policy_from_tags(obj.tags).mode,
                },
            )
        )
        graph.pinned_ids.append(obj.id)
        graph.add_effect(
            RenderEffect(
                kind="module",
                token=obj.id,
                result=role,
                source_component_id=component_id,
            )
        )


def _template_companion_id(module_id: str) -> str | None:
    """Return ``<key>._template`` for a module id, where ``<key>`` is the
    part after the **last** ``.`` (e.g. ``design.encounter`` →
    ``encounter._template``).  Returns ``None`` for ids without a ``.``.
    """
    if "." not in module_id:
        return None
    key = module_id.rsplit(".", 1)[1]
    if not key:
        return None
    return f"{key}._template"


class ParticipantTransform:
    """Represent operator participants as graph metadata/components."""

    name = "participant"

    def __init__(self, *, participants: dict[str, str]) -> None:
        self._participants = {
            key: value.strip()
            for key, value in participants.items()
            if value.strip()
        }

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        for role, kb_id in self._participants.items():
            component_id = f"participant:{role}:{kb_id}"
            graph.metadata[f"participant:{role}"] = kb_id
            if graph.component_by_id(component_id) is not None:
                continue
            graph.add_component(
                CrawlComponent(
                    id=component_id,
                    kind="participant",
                    text=kb_id,
                    role="log",
                    source=ComponentSource(
                        kind="transform",
                        identifier=self.name,
                        metadata={"role": role, "kb_id": kb_id},
                    ),
                    visibility={"log"},
                    metadata={"role": role, "kb_id": kb_id},
                )
            )
        return graph
