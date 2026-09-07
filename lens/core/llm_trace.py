"""Per-generation diagnostics, persisted into the narrative as a stripped comment.

What a generation actually cost is knowable only from the provider's own
response, and until now Lens logged it at INFO and threw it away.  The numbers
that matter — `prompt_tokens`, and above all `cached_tokens` — are the ground
truth behind every claim `lens explain` makes: explain estimates tokens from
character counts (``DEFAULT_CHARS_PER_TOKEN``) and labels blocks `prefix` or
`volatile` from *where they sit in the prompt*.  Both are models of reality.
A trace is the measurement.

The block is a markdown reference-style comment, so it never reaches a model:
``strip_markdown_comments`` removes it from the ``[CURRENT PASSAGE]`` the
operator assembles, and the strip is structural — any ``[…]: #`` block goes,
whether or not it parses as an annotation.  This one deliberately does *not*
parse as one: ``ANNOTATION_RE`` requires ``[a-zA-Z_][a-zA-Z0-9_]*`` for the
operator token, and the hyphen in ``llm-trace`` puts it outside that grammar,
so cursor detection and ``detect_operator_name`` cannot mistake a trace for an
open block.

It is written for a machine to read back, so the body is strict YAML at a fixed
two-space indent — which is also what keeps the block well-formed, since a
multi-line markdown comment continues only while its lines are indented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["LlmTrace", "TraceMode", "parse_trace_mode"]

TraceMode = str
"""``"off"`` | ``"stats"`` | ``"full"`` — see :func:`parse_trace_mode`."""

_VALID_MODES = ("off", "stats", "full")

# A line ending in ``]: #`` closes a markdown comment block (``_COMMENT_END`` is
# a *search*, not a full match).  Reasoning text is model output and may contain
# anything, so any line that would terminate the block early is defused before
# it goes in — otherwise the trace ends there and everything after it becomes
# visible prose in the passage, which is the one failure this channel must not
# have.
#
# Padding with whitespace does NOT work: the pattern is ``\s*$``, so a trailing
# space is still a match.  Only a non-whitespace character after the ``#``
# breaks it, hence the appended marker.
_BLOCK_BREAKER = re.compile(r"\]:\s*#\s*$")
_DEFUSED_SUFFIX = "(defused)"

# The block must contain NO blank line.  ``[label]: #`` is a CommonMark link
# reference definition — which is why every markdown renderer hides an
# annotation block without anyone writing code to strip it — but a link label
# may not span a blank line, so a single blank line inside turns the whole block
# back into ordinary prose and the trace is rendered to the reader.
#
# Measured against markdown-it, not assumed: a 1100-character label still hides,
# a hyphenated key still hides, one blank line leaks.  Model reasoning arrives in
# paragraphs, so this is the common case rather than an edge case.
_BLANK_LINE = re.compile(r"^[ \t]*$")


def parse_trace_mode(raw: object) -> TraceMode:
    """Normalise a configured ``llm_trace`` value; unknown values mean ``"off"``."""
    if raw is True:
        return "stats"
    if raw is False or raw is None:
        return "off"
    text = str(raw).strip().lower()
    return text if text in _VALID_MODES else "off"


def _block_safe_lines(text: str) -> list[str]:
    """Lines of *text* that are safe inside a markdown comment block.

    Two hazards, both from free-form model output: a line that would close the
    block early, and a blank line that would stop the block being a link
    reference definition at all.  Blank lines are dropped rather than filled, so
    the text stays one line per paragraph and readable in a diff.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if _BLANK_LINE.match(line):
            continue
        out.append(line + _DEFUSED_SUFFIX if _BLOCK_BREAKER.search(line) else line)
    return out


@dataclass
class LlmTrace:
    """What one generation cost, as reported by the provider."""

    model: str = ""
    host: str = ""
    elapsed_ms: int = 0
    rounds: int = 1
    temperature: float | None = None
    thinking: bool = False
    reasoning_effort: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_chars: int = 0
    reasoning: str = ""
    """Raw thinking stream. Only rendered in ``"full"`` mode."""

    usage_reported: bool = False
    """False when the provider sent no usage block — the numbers are then absent, not zero."""

    interrupted: bool = False
    tool_calls: list[str] = field(default_factory=lambda: list[str]())

    def has_content(self) -> bool:
        """True when there is a measurement worth recording.

        A generation that reported no usage and produced no thinking has nothing
        to say that the passage does not already show, so it writes no block —
        which is also what keeps traces out of fake-LLM test fixtures.
        """
        return self.usage_reported or self.reasoning_chars > 0

    def render(self, mode: TraceMode = "stats") -> str:
        """The ``[llm-trace …]: #`` block, or ``""`` when there is nothing to say."""
        if mode == "off" or not self.has_content():
            return ""

        lines: list[str] = ["[llm-trace"]
        add = lines.append

        if self.model:
            add(f"  model: {self.model}")
        if self.host:
            add(f"  host: {self.host}")
        add(f"  elapsed_ms: {self.elapsed_ms}")
        if self.rounds != 1:
            add(f"  rounds: {self.rounds}")
        if self.temperature is not None:
            add(f"  temperature: {self.temperature}")
        add(f"  thinking: {str(self.thinking).lower()}")
        if self.thinking and self.reasoning_effort:
            add(f"  reasoning_effort: {self.reasoning_effort}")
        if self.interrupted:
            add("  interrupted: true")
        if self.tool_calls:
            add("  tool_calls:")
            for name in self.tool_calls:
                add(f"    - {name}")

        # Absent rather than zero: a provider that reports no usage is telling
        # us nothing, and a zero here would be read back as a measurement.
        if self.usage_reported:
            add("  usage:")
            for key, value in (
                ("prompt_tokens", self.prompt_tokens),
                ("completion_tokens", self.completion_tokens),
                ("total_tokens", self.total_tokens),
                ("cached_tokens", self.cached_tokens),
            ):
                if value is not None:
                    add(f"    {key}: {value}")
            # Only when something was actually cached: a 0% line on every
            # trace is noise, and the raw `cached_tokens: 0` already says it.
            if self.prompt_tokens and self.cached_tokens:
                pct = round(100.0 * self.cached_tokens / self.prompt_tokens, 1)
                add(f"    cached_pct: {pct}")

        if self.reasoning_chars:
            add("  reasoning:")
            add(f"    chars: {self.reasoning_chars}")
            if mode == "full" and self.reasoning.strip():
                add("    text: |")
                for line in _block_safe_lines(self.reasoning):
                    add(f"      {line}")

        add("]: #")
        return "\n".join(lines) + "\n"
