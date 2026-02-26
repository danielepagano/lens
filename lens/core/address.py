"""Narrative address: typed, CLI-safe location in the narrative tree."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lens.core.narrative import NarrativeNode

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_CURSOR_REF = "/@cursor"


def _validate_slug(slug: str) -> bool:
    return bool(_SLUG_PATTERN.fullmatch(slug))


@dataclass(frozen=True)
class NarrativeAddress:
    """Address for a node, line range, or operator in the narrative tree.

    Format: [<narrative>/]<key>[/<key>...][@<line>[:<line_end>]][#<operator>[:<op_id>]]

    - narrative=None means use active narrative (from lens.toml)
    - cursor=True when parsed from "/@cursor" shorthand
    """

    narrative: str | None
    key_path: tuple[str, ...]
    line: int | None = None
    line_end: int | None = None
    operator: str | None = None
    op_id: str | None = None
    cursor: bool = False

    def __str__(self) -> str:
        if self.cursor:
            return _CURSOR_REF
        if self.narrative is not None:
            path_str = (
                self.narrative + "/" + "/".join(self.key_path)
                if self.key_path
                else self.narrative
            )
        else:
            path_str = "/" + "/".join(self.key_path) if self.key_path else "/"
        suffix = ""
        if self.line is not None:
            suffix += f"@{self.line}"
            if self.line_end is not None:
                suffix += f":{self.line_end}"
        if self.operator is not None:
            suffix += f"#{self.operator}"
            if self.op_id is not None:
                suffix += f":{self.op_id}"
        return path_str + suffix

    def node_only(self) -> NarrativeAddress:
        """Return address with line and operator info stripped."""
        return NarrativeAddress(
            narrative=self.narrative,
            key_path=self.key_path,
            cursor=self.cursor,
        )

    def with_narrative(self, narrative: str) -> NarrativeAddress:
        """Return address with narrative filled in (replaces None)."""
        return NarrativeAddress(
            narrative=narrative,
            key_path=self.key_path,
            line=self.line,
            line_end=self.line_end,
            operator=self.operator,
            op_id=self.op_id,
            cursor=self.cursor,
        )

    @classmethod
    def parse(cls, s: str) -> NarrativeAddress:
        """Parse address string. Raises ValueError on invalid input."""
        s = s.strip()
        if not s:
            raise ValueError("empty address")
        if s == _CURSOR_REF:
            return cls(narrative=None, key_path=(), cursor=True)
        op_part = ""
        if "#" in s:
            idx = s.index("#")
            op_part = s[idx + 1 :]
            s = s[:idx]
        line_start: int | None = None
        line_end: int | None = None
        if "@" in s:
            idx = s.rindex("@")
            line_spec = s[idx + 1 :]
            s = s[:idx]
            if ":" in line_spec:
                a, b = line_spec.split(":", 1)
                try:
                    line_start = int(a)
                    line_end = int(b)
                except ValueError:
                    raise ValueError(f"invalid line range: {line_spec}")
            else:
                if line_spec == "cursor":
                    return cls(narrative=None, key_path=(), cursor=True)
                try:
                    line_start = int(line_spec)
                except ValueError:
                    raise ValueError(f"invalid line: {line_spec}")
        operator: str | None = None
        op_id: str | None = None
        if op_part:
            if ":" in op_part:
                operator, op_id = op_part.split(":", 1)
            else:
                operator = op_part
            if not _validate_slug(operator):
                raise ValueError(f"invalid operator: {operator}")
            if op_id is not None and not _validate_slug(op_id):
                raise ValueError(f"invalid op_id: {op_id}")
        narrative: str | None = None
        key_path: tuple[str, ...]
        if s.startswith("/"):
            s = s[1:]
            narrative = None
            if not s:
                key_path = ()
            else:
                slugs = s.split("/")
                for slug in slugs:
                    if not _validate_slug(slug):
                        raise ValueError(f"invalid slug: {slug}")
                key_path = tuple(slugs)
        else:
            slugs = s.split("/")
            if not slugs or not slugs[0]:
                raise ValueError(f"invalid path: {s}")
            for slug in slugs:
                if not _validate_slug(slug):
                    raise ValueError(f"invalid slug: {slug}")
            narrative = slugs[0]
            key_path = tuple(slugs[1:]) if len(slugs) > 1 else ()
        return cls(
            narrative=narrative,
            key_path=key_path,
            line=line_start,
            line_end=line_end,
            operator=operator,
            op_id=op_id,
        )

    @classmethod
    def from_file_and_annotation(
        cls,
        file: str,
        operator: str | None = None,
        op_id: str | None = None,
        line: int | None = None,
        line_end: int | None = None,
    ) -> NarrativeAddress:
        """Build address from git-relative file path (e.g. narrative/test/_node.md)."""
        if not file.startswith("narrative/"):
            raise ValueError(f"expected narrative path, got: {file}")
        rest = file[len("narrative/") :]
        parts = rest.split("/")
        if not parts:
            raise ValueError(f"invalid narrative path: {file}")
        narrative = parts[0]
        if len(parts) == 1:
            key_path = ()
        elif parts[-1] == "_node.md":
            key_path = tuple(parts[1:-1])
        elif parts[-1].endswith(".md"):
            key_path = tuple(parts[1:-1]) + (parts[-1][:-3],)
        else:
            key_path = tuple(parts[1:])
        return cls(
            narrative=narrative,
            key_path=key_path,
            line=line,
            line_end=line_end,
            operator=operator,
            op_id=op_id,
        )

    def to_node(self, project_root: Path) -> NarrativeNode:
        """Construct NarrativeNode from this address. Requires narrative to be set."""
        if self.narrative is None:
            raise ValueError("cannot resolve node: narrative not set")
        from lens.core.narrative import NarrativeNode

        narrative_dir = project_root / "narrative" / self.narrative
        return NarrativeNode(narrative_root=narrative_dir, key_path=self.key_path)
