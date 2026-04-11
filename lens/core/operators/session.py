"""SessionOperator: base class for operators that manage sub-node sessions.

Session operators (``design``, ``play``) create a sub-node the first time they
are invoked and continue working inside it on subsequent calls.  They support
*modules* — KB objects with a configurable prefix that are pinned one-at-a-time
into the session sub-node front matter.

Subclasses override :meth:`_run_fresh` and :meth:`_run_inside` to define how
generation works, and optionally :meth:`run_session_end` for custom close
behaviour.

Session lifecycle
-----------------
*  First call → :meth:`_setup_fresh_session` creates the sub-node, pins
   :attr:`auto_pins` and optional module, stages, then delegates to
   :meth:`_run_fresh`.
*  Subsequent calls inside the session → :meth:`_run_inside` (continue or
   retry).  Front-matter is updated when ``--module`` changes or new
   pins/unpins are supplied.
*  ``--end`` → :meth:`run_session_end` appends the close tag to the parent.

Module handling
---------------
``--module <key>`` pins ``<module_prefix><key>`` in the sub-node front matter.
Only one module is active at a time: switching ``--module`` removes all
``<module_prefix>*`` pins before adding the new one.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

from lens.core.annotations import parse_front_matter, strip_markdown_comments
from lens.core.context import CrawlResult, crawl
from lens.core.llm import generate_text
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator, OperatorError
from lens.core.prompts import PromptStore
from lens.core.pinning import pin as pin_node
from lens.core.pinning import remove_pin
from lens.core.pinning import unpin as unpin_node
from lens.core.project import ProjectSession, validate_slug
from lens.core.storage import Storage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NONSLUG_RE = re.compile(r"[^a-z0-9]+")


def prompt_to_slug(prompt: str, max_words: int = 5) -> str:
    """Convert prompt text to a hyphen-joined slug of up to *max_words* words."""
    words = _NONSLUG_RE.sub(" ", prompt.lower()).split()
    return "-".join(words[:max_words])


# ---------------------------------------------------------------------------
# Shared summary block formatting
# ---------------------------------------------------------------------------

MAX_SUMMARY_TITLE_WORDS = 10
"""Maximum number of words allowed in a summary title."""

SUMMARY_COMMENT_TAG = "section"
"""HTML comment tag prefix written above every summary block.

All operators that summarize use the same tag so the LLM can deterministically
recognize a summary block in context (annotations are stripped from LLM
context, but HTML comments are preserved)."""

_SLUG_OPERATOR_PREFIXES = (
    "section-",
    "play-",
    "design-",
    "collate-",
    "advance-day-",
    "advance-",
)


class SummaryTitleError(OperatorError):
    """Raised when raw summary text lacks a valid first-line title (see :func:`format_summary_block`)."""


def slug_for_summary_prompt(slug: str) -> str:
    """Strip a leading session-operator slug prefix for LLM titling instructions only.

    The HTML ``<!-- section:<slug> -->`` comment always uses the full storage
    slug; prompts pass this shortened value as ``{slug}`` so the model titles
    the meaningful segment (e.g. ``play-amy-dream`` → ``amy-dream``).
    """
    for prefix in _SLUG_OPERATOR_PREFIXES:
        if slug.startswith(prefix):
            return slug[len(prefix) :]
    return slug


_TITLE_LEADING_MARKERS = re.compile(r'^[#>\*_\s"\'`]+')
_TITLE_TRAILING_MARKERS = re.compile(r'[\*_"\'`\s]+$')


def _extract_title_candidate(line: str) -> str:
    """Strip markdown/quote/bold markers from a candidate title line."""
    s = _TITLE_LEADING_MARKERS.sub("", line.strip())
    s = _TITLE_TRAILING_MARKERS.sub("", s)
    return s.rstrip(":").strip()


def _blockquote_body(lines: list[str]) -> list[str]:
    """Format the summary body as one continuous Markdown blockquote.

    Every line is written as ``> …``; blank lines use ``> `` so the blockquote
    does not break. Leading ``>`` runts on each line are stripped first so
    lines are not double-quoted.
    """
    out: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if not stripped.strip():
            out.append("> ")
            continue
        s = stripped
        while s.startswith(">"):
            s = s[1:]
            if s.startswith(" "):
                s = s[1:]
        suffix = s
        out.append(f"> {suffix}" if suffix else "> ")
    return out


def format_summary_block(slug: str, raw_summary: str) -> str:
    """Format raw summary text into the canonical Lens summary block.

    Canonical shape::

        <!-- section:<slug> -->

        ### <Title>

        > body line 1
        > body line 2

    Algorithmic normalization applied:

    - **Title**: the first non-empty line is the title after stripping markdown
      markers (``#``, ``>``, ``**``, quotes). It must be non-empty and have at
      most :data:`MAX_SUMMARY_TITLE_WORDS` words; otherwise
      :exc:`SummaryTitleError` is raised (callers retry the LLM or surface the
      error).
    - **Body**: lines after the title, trimmed of leading/trailing blank lines,
      then passed through :func:`_blockquote_body` so the body is one blockquote
      run (blank lines are ``> ``).
    - Exactly one blank line sits between the HTML comment and the ``###``
      header, and between the header and the body.

    The HTML comment always uses the full storage *slug*; LLM prompts may use
    :func:`slug_for_summary_prompt` for the ``{slug}`` template field only.
    """
    text = (raw_summary or "").strip()
    lines = text.split("\n") if text else []

    first_idx = 0
    while first_idx < len(lines) and not lines[first_idx].strip():
        first_idx += 1

    if first_idx >= len(lines):
        raise SummaryTitleError("summary text is empty")

    candidate = _extract_title_candidate(lines[first_idx])
    if not candidate:
        raise SummaryTitleError("summary has no usable first-line title")
    title_words = candidate.split()
    if len(title_words) > MAX_SUMMARY_TITLE_WORDS:
        raise SummaryTitleError(
            f"summary title exceeds {MAX_SUMMARY_TITLE_WORDS} words "
            f"({len(title_words)} words)"
        )

    title = candidate
    body_lines = lines[first_idx + 1 :]

    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    quoted = _blockquote_body(body_lines)

    parts = [
        f"<!-- {SUMMARY_COMMENT_TAG}:{slug} -->",
        "",
        f"### {title}",
        "",
        *quoted,
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Shared summary generation
# ---------------------------------------------------------------------------

def build_summary_messages(
    crawl_result: CrawlResult,
    content: str,
    *,
    slug: str,
    system_key: str = "session.summary_system",
    instruction_key: str = "session.summary_instruction_template",
) -> list[dict[str, str]]:
    """Build LLM messages for summarizing section/session content.

    The instruction template receives ``content`` and ``slug``. The ``slug``
    value is :func:`slug_for_summary_prompt` output so titling examples match
    what the model sees; :func:`format_summary_block` still writes the full
    storage slug in the HTML comment.
    """
    from lens.core.context import assemble_prompt

    prompts = PromptStore(crawl_result.project_root)
    prompt_slug = slug_for_summary_prompt(slug)
    instruction = prompts.format(
        instruction_key, content=content, slug=prompt_slug
    )
    return assemble_prompt(
        crawl_result,
        system_prompt=prompts.get(system_key),
        instruction=instruction,
    )


async def generate_summary_block(
    *,
    slug: str,
    crawl_result: CrawlResult,
    content: str,
    project_root: Path,
    operator_name: str,
    llm_id: str | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: Any | None = None,
    reasoning: str | None = None,
    system_key: str = "session.summary_system",
    instruction_key: str = "session.summary_instruction_template",
    max_attempts: int = 2,
) -> str:
    """Generate an LLM summary and return a fully formatted summary block.

    Calls the LLM up to *max_attempts* times until :func:`format_summary_block`
    accepts the first line as a title. Raises :exc:`SummaryTitleError` if every
    attempt yields text but the title rule still fails. Raises
    :exc:`OperatorError` if every attempt returns empty or whitespace-only
    output.
    """
    attempts = max(1, max_attempts)
    last_title_error: SummaryTitleError | None = None
    for _ in range(attempts):
        messages = build_summary_messages(
            crawl_result,
            content,
            slug=slug,
            system_key=system_key,
            instruction_key=instruction_key,
        )
        raw = (
            await generate_text(
                messages,
                project_root,
                llm_id=llm_id,
                cancel_event=cancel_event,
                on_preview=on_token,
                interrupt_policy="raise",
                operator_name=operator_name,
                reasoning=reasoning,
            )
        ).strip()
        if not raw:
            continue
        try:
            return format_summary_block(slug, raw)
        except SummaryTitleError as exc:
            last_title_error = exc
            continue
    if last_title_error is not None:
        raise last_title_error
    raise OperatorError(
        "summary LLM returned empty or whitespace-only output after "
        f"{attempts} attempt(s)"
    )


# ---------------------------------------------------------------------------
# SessionOperator base
# ---------------------------------------------------------------------------


class SessionOperator(Operator):
    """Base for operators that manage sub-node sessions with module support."""

    requires_id: ClassVar[bool] = True

    module_prefix: ClassVar[str] = ""
    """KB id prefix for modules (e.g. ``"design."`` or ``"rules."``).

    When the user passes ``--module <key>``, the full KB id is
    ``module_prefix + key``.  Only one module pin (matching the prefix) is
    active at a time.
    """

    auto_pins: ClassVar[list[str]] = []
    """KB ids pinned automatically when a fresh session is created."""

    @classmethod
    def _companion_pin_for_module(
        cls, session: ProjectSession, module_key: str
    ) -> str | None:
        """Optional extra KB id to pin alongside ``module_prefix + module_key``.

        Subclasses may pin a related object (e.g. ``type._template``) when it
        exists.  Default: no companion.
        """
        return None

    # ------------------------------------------------------------------
    # Session detection
    # ------------------------------------------------------------------

    @classmethod
    def find_active_session(
        cls, narrative: NarrativeNode
    ) -> tuple[NarrativeNode | None, str | None]:
        """Return ``(session_node, session_id)`` if cursor is inside a session.

        The cursor is *inside* a session when the parent of the cursor node
        has an unclosed ``[<operator>:<id>]: #`` annotation.
        """
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            return None, None
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        try:
            parent_text = parent.md_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return None, None
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if open_ann is not None and open_ann.operator == cls.name:
            return cursor, open_ann.id
        return None, None

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    @classmethod
    def generate_session_id(
        cls,
        prompt: str | None,
        module_id: str | None,
        parent: NarrativeNode,
    ) -> str:
        """Auto-generate a unique session sub-node id.

        Pattern: ``<name>[-module_id][-prompt_slug]`` with a numeric suffix
        when a sub-node with that name already exists.
        """
        parts = [cls.name]
        if module_id:
            parts.append(module_id.strip())
        if prompt:
            slug = prompt_to_slug(prompt)
            if slug:
                parts.append(slug)
        base = "-".join(parts)
        existing = set(parent.child_keys())
        if base not in existing:
            return base
        n = 1
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    # ------------------------------------------------------------------
    # Front-matter / module helpers
    # ------------------------------------------------------------------

    @classmethod
    def _update_front_matter_for_call(
        cls,
        node: NarrativeNode,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        storage: Storage,
        session: ProjectSession,
    ) -> None:
        """Update front matter for a subsequent call.

        - If *module_id* is provided and :attr:`module_prefix` is set, remove
          all existing ``<prefix>*`` pins and add the new module pin.
        - Merge any extra *pins* / *unpins*.
        """
        if module_id and cls.module_prefix:
            fm = parse_front_matter(
                node.md_path().read_text(encoding="utf-8")
            )
            kb_pins: list[str] = [
                str(p) for p in (fm.get("kb_pin") or [])  # type: ignore[union-attr]
            ]
            old_module_pins = [
                p for p in kb_pins if p.startswith(cls.module_prefix)
                and p not in cls.auto_pins
            ]
            drop_companions: list[str] = []
            for p in old_module_pins:
                old_key = p.removeprefix(cls.module_prefix)
                if old_key and old_key != module_id:
                    cid = cls._companion_pin_for_module(session, old_key)
                    if cid and cid in kb_pins:
                        drop_companions.append(cid)
            if drop_companions:
                remove_pin(node, drop_companions, storage)
            if old_module_pins:
                remove_pin(node, old_module_pins, storage)
            new_module_kb_id = cls.module_prefix + module_id
            if not session.kb.exists(new_module_kb_id):
                raise OperatorError(
                    f"module does not exist: {new_module_kb_id}"
                )
            pin_node(node, [new_module_kb_id], storage)
            new_companion = cls._companion_pin_for_module(session, module_id)
            if new_companion:
                pin_node(node, [new_companion], storage)
        if pins:
            pin_node(node, pins, storage)
        if unpins:
            unpin_node(node, unpins, storage)

    # ------------------------------------------------------------------
    # Fresh session setup
    # ------------------------------------------------------------------

    @classmethod
    async def _setup_fresh_session(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        slug: str | None = None,
    ) -> tuple[NarrativeNode, Storage]:
        """Create a sub-node, pin auto_pins + module, stage setup.

        Returns ``(child_node, storage)`` so the caller can create inline
        storage keyed to the child.
        """
        cursor = narrative.find_cursor()
        if slug is not None:
            if not validate_slug(slug):
                raise OperatorError(
                    f"invalid slug '{slug}' (alphanumeric, underscores, hyphens only)"
                )
            # Auto-prepend operator prefix (e.g. "design-", "play-") if absent,
            # keeping session slugs consistent with auto-generated ones.
            prefix = f"{cls.name}-"
            if not slug.startswith(prefix):
                slug = prefix + slug
            if slug in set(cursor.child_keys()):
                raise OperatorError(
                    f"a node named '{slug}' already exists here"
                )
            session_id = slug
        else:
            session_id = cls.generate_session_id(prompt, module_id, cursor)

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(session_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        child_node = op.create_subnode(cursor, session_id)

        # Auto-pins + user pins + module.
        all_pins = list(cls.auto_pins) + list(pins)
        if module_id and cls.module_prefix:
            module_kb_id = cls.module_prefix + module_id
            if not session.kb.exists(module_kb_id):
                raise OperatorError(
                    f"module does not exist: {module_kb_id}"
                )
            all_pins.append(module_kb_id)
            companion = cls._companion_pin_for_module(session, module_id)
            if companion:
                all_pins.append(companion)
        if all_pins:
            pin_node(child_node, all_pins, storage)
        if unpins:
            unpin_node(child_node, unpins, storage)

        storage.stage_all()

        if on_stream_target is not None:
            await on_stream_target(str(child_node.to_address()))

        return child_node, storage

    # ------------------------------------------------------------------
    # Abstract generation hooks
    # ------------------------------------------------------------------

    @classmethod
    async def _run_fresh(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        setup_storage: Storage,
        prompt: str | None,
        llm_id: str | None,
        reasoning: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> Any:
        """Run generation in a freshly created session sub-node.

        *node* is the newly created child; front matter is already set and
        staged.  Subclasses implement the actual generation logic.
        """
        raise NotImplementedError  # pragma: no cover

    @classmethod
    async def _run_inside(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        prompt: str | None,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        reasoning: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> Any:
        """Run generation inside an existing session sub-node.

        Front-matter updates (module swap, extra pins/unpins) are handled
        by the caller before this method; subclasses implement the generation.
        """
        raise NotImplementedError  # pragma: no cover

    # ------------------------------------------------------------------
    # Session end
    # ------------------------------------------------------------------

    summarize_on_end: ClassVar[bool] = False
    """When True, ``run_session_end`` generates an LLM summary of the session
    content and appends the canonical block (HTML comment, ``###`` title,
    one blockquoted body) before the close tag."""

    # Keys for :func:`build_summary_messages` when ``summarize_on_end`` runs.
    summary_system_prompt_key: ClassVar[str] = "session.summary_system"
    summary_instruction_prompt_key: ClassVar[str] = "session.summary_instruction_template"

    @classmethod
    async def run_session_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        llm_id: str | None = None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Any:
        """Close the current session.

        Verifies the cursor is inside the session sub-node.  When
        :attr:`summarize_on_end` is True, generates an LLM summary of the
        session content and appends the canonical summary block before the
        close tag. Override for fully custom close behaviour (e.g. KB extraction).
        """
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise OperatorError(
                f"no open {cls.name} to close (cursor at root)"
            )
        id = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text(encoding="utf-8")
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if (
            open_ann is None
            or open_ann.operator != cls.name
            or open_ann.id != id
        ):
            raise OperatorError(
                f"parent does not have unclosed [{cls.name}:{id}]: # — "
                "cursor must be in the session sub-node"
            )
        rel_path = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        if storage.has_pending() and storage.detect_pending_owner() == owner:
            storage.stage_all()
        op = cls(storage, narrative)

        summary = ""
        if cls.summarize_on_end:
            child_text = cursor.md_path().read_text(encoding="utf-8")
            child_clean = strip_markdown_comments(child_text).strip()
            if child_clean:
                crawl_result = crawl(parent)
                summary = await generate_summary_block(
                    slug=id,
                    crawl_result=crawl_result,
                    content=child_clean,
                    project_root=session.project_root,
                    operator_name=cls.name,
                    llm_id=llm_id,
                    on_token=on_token,
                    cancel_event=cancel_event,
                    reasoning=reasoning,
                    system_key=cls.summary_system_prompt_key,
                    instruction_key=cls.summary_instruction_prompt_key,
                )

        op.close_subnode(parent, id, summary)
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @classmethod
    async def run_session(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None = None,
        module_id: str | None = None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None = None,
        reasoning: str | None = None,
        retry: bool = False,
        end: bool = False,
        slug: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run a session (create, continue, or end).

        Routes to :meth:`run_session_end`, :meth:`_run_inside`, or
        :meth:`_run_fresh` depending on state.
        """
        if end:
            return await cls.run_session_end(
                session=session, narrative=narrative,
                llm_id=llm_id, reasoning=reasoning, on_token=on_token,
                cancel_event=cancel_event,
            )

        session_node, _ = cls.find_active_session(narrative)

        if session_node is not None:
            if slug is not None:
                raise OperatorError(
                    "--slug can only be used when starting a new session"
                )
            return await cls._run_inside(
                session=session,
                narrative=narrative,
                node=session_node,
                prompt=prompt,
                module_id=module_id,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                reasoning=reasoning,
                retry=retry,
                on_token=on_token,
                cancel_event=cancel_event,
                **kwargs,
            )
        else:
            node, setup_storage = await cls._setup_fresh_session(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=module_id,
                pins=pins,
                unpins=unpins,
                on_stream_target=on_stream_target,
                slug=slug,
            )
            return await cls._run_fresh(
                session=session,
                narrative=narrative,
                node=node,
                setup_storage=setup_storage,
                prompt=prompt,
                llm_id=llm_id,
                reasoning=reasoning,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
                **kwargs,
            )
