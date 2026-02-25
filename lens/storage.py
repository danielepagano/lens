"""Git-backed transactional storage for Lens projects.

Transactions map to git working-tree state:
- Pending transaction = unstaged changes (modifications + untracked files)
- Committing a transaction = git add -A (staging all changes)
- Rolling back = discarding unstaged changes
- Checkpoint = stage + git commit

The Storage class is instantiated with an ``owner`` NarrativeAddress that identifies
which operator (or system command) is making changes.  On the first write
operation Storage checks whether any pending unstaged changes belong to a
*different* owner and, if so, stages them automatically before proceeding.

Owner format: NarrativeAddress with operator/op_id/line set as appropriate.
System / non-operator commands use ``None`` (always stages pending first).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import ClassVar

from lens.address import NarrativeAddress
from lens.annotations import ANNOTATION_OPEN_RE, ANNOTATION_RE

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"
)


def detect_pending_owner_from_diff(diff_text: str) -> NarrativeAddress | None:
    """Parse ``git diff`` output and return the owner address of the first
    operator annotation found, or ``None`` if no annotation appears."""
    current_file: str | None = None
    new_line = 0
    old_line = 0

    added_owner: NarrativeAddress | None = None
    removed_owner: NarrativeAddress | None = None

    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            continue
        if raw.startswith("--- "):
            continue
        hm = _HUNK_HEADER_RE.match(raw)
        if hm:
            old_line = int(hm.group(1))
            new_line = int(hm.group(2))
            continue
        if current_file is None:
            continue

        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:]
            if added_owner is None:
                owner = _match_annotation_owner(content, current_file, new_line)
                if owner is not None:
                    added_owner = owner
            new_line += 1
            continue

        if raw.startswith("-") and not raw.startswith("---"):
            content = raw[1:]
            if removed_owner is None:
                owner = _match_annotation_owner(content, current_file, old_line)
                if owner is not None:
                    removed_owner = owner
            old_line += 1
            continue

        if not raw.startswith("\\") and not raw.startswith("diff "):
            new_line += 1
            old_line += 1

    # Prefer added annotations (modes 1 & 2) over removed (mode 3).
    return added_owner or removed_owner


def _match_annotation_owner(
    line: str, file: str, line_no: int
) -> NarrativeAddress | None:
    """If *line* matches an operator annotation open pattern, return the
    corresponding owner address, or ``None`` for non-narrative files."""
    for regex in (ANNOTATION_RE, ANNOTATION_OPEN_RE):
        m = regex.match(line.strip())
        if m is None:
            continue
        if m.group("close"):
            continue
        if m.group("self_close"):
            continue
        operator: str = m.group("operator")
        ann_id: str | None = m.group("id")
        line_arg = line_no if ann_id is None else None
        try:
            return NarrativeAddress.from_file_and_annotation(
                file, operator=operator, op_id=ann_id, line=line_arg
            )
        except ValueError:
            return None
    return None


class Storage:
    """Git-backed transactional storage.

    Parameters
    ----------
    git_root:
        Path to the repository root (must contain ``.git``).
    owner:
        NarrativeAddress for the caller.  ``None`` for system /
        non-operator commands (they never continue a pending transaction).
    """

    _GIT: ClassVar[str] = "git"

    def __init__(self, git_root: Path, owner: NarrativeAddress | None = None) -> None:
        self._root = git_root
        self._owner = owner
        self._ownership_checked = False

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Git state queries
    # ------------------------------------------------------------------

    def has_pending(self) -> bool:
        """Return ``True`` if there are unstaged modifications or untracked
        files (i.e. a pending transaction exists)."""
        tracked = subprocess.run(
            [self._GIT, "diff", "--quiet"],
            cwd=self._root,
            capture_output=True,
        )
        if tracked.returncode != 0:
            return True
        untracked = subprocess.run(
            [self._GIT, "ls-files", "--others", "--exclude-standard"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return bool(untracked.stdout.strip())

    def pending_files(self) -> list[str]:
        """List files with unstaged changes or that are untracked."""
        result: list[str] = []
        diff = subprocess.run(
            [self._GIT, "diff", "--name-only"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        result.extend(line for line in diff.stdout.strip().splitlines() if line)
        untracked = subprocess.run(
            [self._GIT, "ls-files", "--others", "--exclude-standard"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        result.extend(line for line in untracked.stdout.strip().splitlines() if line)
        return result

    def diff(self) -> str:
        """Return the raw ``git diff`` (unstaged changes to tracked files)."""
        r = subprocess.run(
            [self._GIT, "diff"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return r.stdout

    def detect_pending_owner(self) -> NarrativeAddress | None:
        """Return the owner of the current pending transaction.

        Checks tracked-file changes via ``git diff`` first, then falls back to
        scanning untracked ``.md`` files for operator annotations.  The fallback
        is needed when an operator creates entirely new files (e.g. the section
        operator promoting a leaf node to a folder), so the annotation never
        appears in the diff.
        """
        owner = detect_pending_owner_from_diff(self.diff())
        if owner is not None:
            return owner
        for rel_path in self.pending_files():
            if not rel_path.endswith(".md"):
                continue
            abs_path = self._root / rel_path
            if not abs_path.is_file():
                continue
            try:
                text = abs_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                addr = _match_annotation_owner(line, rel_path, lineno)
                if addr is not None:
                    return addr
        return None

    # ------------------------------------------------------------------
    # Transaction lifecycle
    # ------------------------------------------------------------------

    def stage_all(self) -> None:
        """Stage every change (``git add -A``), committing the transaction."""
        subprocess.run(
            [self._GIT, "add", "-A"],
            cwd=self._root,
            check=True,
            capture_output=True,
        )
        self._ownership_checked = False

    def rollback(self) -> None:
        """Discard all unstaged changes and remove untracked files."""
        subprocess.run(
            [self._GIT, "checkout", "--", "."],
            cwd=self._root,
            capture_output=True,
        )
        subprocess.run(
            [self._GIT, "clean", "-fd"],
            cwd=self._root,
            capture_output=True,
        )
        self._ownership_checked = False

    def checkpoint(self, message: str) -> None:
        """Stage everything and create a git commit."""
        self.stage_all()
        subprocess.run(
            [self._GIT, "commit", "-m", message],
            cwd=self._root,
            check=True,
            capture_output=True,
        )

    # ------------------------------------------------------------------
    # File write operations — all trigger ownership check on first call
    # ------------------------------------------------------------------

    def write_file(self, path: Path, content: str) -> None:
        self._ensure_ownership()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_file_bytes(self, path: Path, data: bytes) -> None:
        self._ensure_ownership()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete_file(self, path: Path) -> None:
        self._ensure_ownership()
        if path.exists():
            path.unlink()

    def mkdir(self, path: Path) -> None:
        self._ensure_ownership()
        path.mkdir(parents=True, exist_ok=True)

    def rmdir(self, path: Path) -> None:
        self._ensure_ownership()
        if path.exists() and path.is_dir():
            path.rmdir()

    def rename(self, src: Path, dst: Path) -> None:
        self._ensure_ownership()
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_ownership(self) -> None:
        """Auto-stage pending changes if they belong to a different owner.

        Called lazily on the first write operation.  System commands
        (``owner=None``) always stage any pending changes.  Operators only
        stage when the detected pending owner differs from ``self._owner``.
        """
        if self._ownership_checked:
            return
        self._ownership_checked = True
        if not self.has_pending():
            return
        if self._owner is None:
            self.stage_all()
            return
        pending_owner = self.detect_pending_owner()
        if pending_owner == self._owner:
            return
        self.stage_all()
