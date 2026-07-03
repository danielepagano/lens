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

import os
import re
import subprocess
from pathlib import Path
from typing import ClassVar

from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.annotations import ANNOTATION_OPEN_RE, ANNOTATION_RE
from lens.core.storage_text import (
    NormalizedStorageText,
    StorageTextNormalizer,
    format_kb_prompt_block_from_normalized,
)

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
        self._text_normalizer = StorageTextNormalizer()

    @property
    def root(self) -> Path:
        return self._root

    def normalize_path_text(self, path: Path) -> NormalizedStorageText:
        """Return cached normalized storage text projections for *path*."""
        return self._text_normalizer.normalize_path(path)

    def normalize_raw_text(
        self, raw_storage_text: str, *, source_id: str | None = None
    ) -> NormalizedStorageText:
        """Return normalized projections for raw text, optionally cache-keyed."""
        return self._text_normalizer.normalize_raw(raw_storage_text, source_id=source_id)

    def llm_view_from_raw_text(
        self, raw_storage_text: str, *, source_id: str | None = None
    ) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        """Return ``(visible_text, disk_start_lines, disk_end_lines)`` for raw text."""
        view = self.normalize_raw_text(raw_storage_text, source_id=source_id).llm_view
        return (
            view.visible_for_llm,
            view.disk_line_start_1based,
            view.disk_line_end_1based,
        )

    def resolve_selection_to_disk_lines(
        self,
        raw_storage_text: str,
        selection: object,
        *,
        source_id: str | None = None,
    ) -> tuple[int, int]:
        """Resolve a line-content selection on LLM-visible text to disk lines."""
        from lens.core.text_select import resolve_selection

        norm = self.normalize_raw_text(raw_storage_text, source_id=source_id).llm_view
        resolved = resolve_selection(norm.visible_for_llm, selection)  # type: ignore[arg-type]
        if resolved.is_cursor:
            raise LensException(
                "selection resolved to an empty range (use cursor splice helpers)"
            )
        n = len(norm.disk_line_start_1based)
        if resolved.slice_end <= resolved.slice_start or resolved.slice_start >= n:
            raise LensException("resolved selection is out of range for storage view")
        last = resolved.slice_end - 1
        return (
            norm.disk_line_start_1based[resolved.slice_start],
            norm.disk_line_end_1based[last],
        )

    def invalidate_normalized_path(self, path: Path) -> None:
        """Evict cached normalization for a file path."""
        self._text_normalizer.invalidate_path(path)

    def invalidate_normalized_source(self, source_id: str) -> None:
        """Evict cached normalization for an in-memory source id."""
        self._text_normalizer.invalidate_source(source_id)

    def format_kb_prompt_block(
        self,
        *,
        canonical_id: str,
        text: str,
        tags: list[str],
        include_comments: bool = False,
        strip_html: bool = False,
        source_id: str | None = None,
    ) -> str:
        """Format KB text via storage-backed normalized cache."""
        normalized = self.normalize_raw_text(text, source_id=source_id)
        return format_kb_prompt_block_from_normalized(
            canonical_id=canonical_id,
            normalized=normalized,
            tags=tags,
            include_comments=include_comments,
            strip_html=strip_html,
        )

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

    def staged_files(self) -> list[str]:
        """List files in the staging area (``git diff --cached --name-only``)."""
        r = subprocess.run(
            [self._GIT, "diff", "--cached", "--name-only"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return [line for line in r.stdout.strip().splitlines() if line]

    def commit_log(self, range_spec: str, max_count: int = 20) -> list[dict[str, str]]:
        """Return commits in *range_spec* as a list of ``{hash, message}`` dicts."""
        r = subprocess.run(
            [self._GIT, "log", "--oneline", f"--max-count={max_count}", range_spec],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            return []
        commits: list[dict[str, str]] = []
        for line in r.stdout.strip().splitlines():
            if not line:
                continue
            short_hash, _, message = line.partition(" ")
            commits.append({"hash": short_hash, "message": message})
        return commits

    def staged_diff(self) -> str:
        """Return the staged diff (``git diff --cached``).

        Represents the *pending checkpoint*: changes staged but not yet committed.
        """
        r = subprocess.run(
            [self._GIT, "diff", "--cached"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return r.stdout

    def pending_diff(self) -> str:
        """Return the full diff of the pending transaction.

        Combines unstaged tracked-file changes (``git diff``) with untracked
        files shown as new-file additions (``git diff --no-index /dev/null
        <file>``).  This gives a complete picture of all un-committed work.
        """
        parts: list[str] = [self.diff()]
        untracked = subprocess.run(
            [self._GIT, "ls-files", "--others", "--exclude-standard"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        for rel_path in untracked.stdout.strip().splitlines():
            if not rel_path:
                continue
            abs_path = self._root / rel_path
            if not abs_path.is_file():
                continue
            r = subprocess.run(
                [self._GIT, "diff", "--no-index", "--", "/dev/null", rel_path],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
            if r.stdout:
                parts.append(r.stdout)
        return "".join(parts)

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
            # Scan for the *last* annotation match: the owner annotation is
            # always appended at the tail of the file (cursor position), so
            # earlier annotations (e.g. a previously-closed [write...] block
            # copied from the old leaf during leaf-to-folder promotion) must
            # not shadow the real owner annotation at the end.
            last_addr: NarrativeAddress | None = None
            for lineno, line in enumerate(text.splitlines(), 1):
                addr = _match_annotation_owner(line, rel_path, lineno)
                if addr is not None:
                    last_addr = addr
            if last_addr is not None:
                return last_addr
        return None

    def detect_staged_owner(self) -> NarrativeAddress | None:
        """Return the owner of a staged mutation claim.

        Checks the staged diff (``git diff --cached``) for edit claim tags.
        This is used to detect mutations where the claim tags are staged but
        no proposal has been written yet (i.e., no unstaged changes).
        """
        return detect_pending_owner_from_diff(self.staged_diff())

    def has_staged(self) -> bool:
        """Return ``True`` if there are staged changes (``git diff --cached``)."""
        r = subprocess.run(
            [self._GIT, "diff", "--cached", "--quiet"],
            cwd=self._root,
            capture_output=True,
        )
        return r.returncode != 0

    def unstage_all(self) -> None:
        """Unstage all staged changes (``git reset HEAD``)."""
        subprocess.run(
            [self._GIT, "reset", "HEAD"],
            cwd=self._root,
            capture_output=True,
        )

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

    def commit(self, message: str) -> None:
        """Stage all changes and create a git commit, if there is anything to commit."""
        self.stage_all()
        has_staged = subprocess.run(
            [self._GIT, "diff", "--cached", "--quiet"],
            cwd=self._root,
            capture_output=True,
        ).returncode != 0
        if has_staged:
            subprocess.run(
                [self._GIT, "commit", "-m", message],
                cwd=self._root,
                check=True,
                capture_output=True,
            )

    def has_remote(self) -> bool:
        """Return True if at least one git remote is configured."""
        r = subprocess.run(
            [self._GIT, "remote"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return bool(r.stdout.strip())

    def get_remote_url(self, remote: str = "origin") -> str:
        """Return the URL for the given git remote."""
        r = subprocess.run(
            [self._GIT, "config", f"remote.{remote}.url"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            raise LensException(f"no remote URL for '{remote}'")
        return r.stdout.strip()

    def _git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def is_working_tree_clean(self) -> bool:
        """True when there is no unstaged, untracked, or staged-but-uncommitted work."""
        return not self.has_pending() and not self.has_staged()

    def has_upstream(self) -> bool:
        """Return True if the current branch has an upstream tracking branch."""
        return self._has_upstream()

    def _has_upstream(self) -> bool:
        r = subprocess.run(
            [self._GIT, "rev-parse", "--verify", "@{upstream}"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        return r.returncode == 0

    def _rev_list_count(self, range_spec: str) -> int:
        r = subprocess.run(
            [self._GIT, "rev-list", "--count", range_spec],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            return 0
        try:
            return int(r.stdout.strip())
        except ValueError:
            return 0

    def needs_fast_forward(self) -> bool:
        """Return True when the remote is ahead of HEAD (new commits to pull)."""
        if not self.has_remote():
            return False
        self.fetch_quiet()
        if not self._has_upstream():
            return False
        return self._rev_list_count("HEAD..@{upstream}") > 0

    def fetch_quiet(self) -> None:
        r = subprocess.run(
            [self._GIT, "fetch", "-q"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            raise LensException(err or "git fetch failed")

    def refresh_fast_forward(self) -> None:
        """Fetch and fast-forward merge to upstream when the remote is ahead."""
        if not self.has_remote():
            raise LensException("no git remote configured")
        self.fetch_quiet()
        if not self._has_upstream():
            raise LensException(
                "no upstream branch; set it on first push (e.g. git push -u <remote> <branch>)"
            )
        if self._rev_list_count("HEAD..@{upstream}") == 0:
            return
        if not self.is_working_tree_clean():
            raise LensException(
                "cannot refresh: uncommitted changes; commit or rollback, or use lens refresh --reset"
            )
        r = subprocess.run(
            [self._GIT, "merge", "--ff-only", "@{upstream}"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            raise LensException(
                "cannot fast-forward; histories diverged. Use `lens refresh --reset` to match "
                "the remote and discard local unpushed commits and uncommitted work, or resolve "
                f"with git. {err}".strip()
            )

    def refresh_reset_hard_to_upstream(self) -> None:
        """Fetch, reset hard to upstream, and remove untracked files."""
        if not self.has_remote():
            raise LensException("no git remote configured")
        self.fetch_quiet()
        if not self._has_upstream():
            raise LensException(
                "no upstream branch; set it on first push (e.g. git push -u <remote> <branch>)"
            )
        r = subprocess.run(
            [self._GIT, "reset", "--hard", "@{upstream}"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            raise LensException(err or "git reset --hard failed")
        c = subprocess.run(
            [self._GIT, "clean", "-fd"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if c.returncode != 0:
            err = (c.stderr or "").strip()
            raise LensException(err or "git clean failed")
        self._ownership_checked = False

    def push_or_raise(self) -> None:
        """Push to upstream; on rejection, fetch and explain remote-ahead vs other failures."""
        r = subprocess.run(
            [self._GIT, "push"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if r.returncode == 0:
            return
        push_err = (r.stderr or "").strip()
        fetch_r = subprocess.run(
            [self._GIT, "fetch", "-q"],
            cwd=self._root,
            capture_output=True,
            text=True,
            env=self._git_env(),
        )
        if fetch_r.returncode != 0:
            fetch_err = (fetch_r.stderr or "").strip()
            msg = f"push failed: {push_err}" if push_err else "push failed"
            if fetch_err:
                msg = f"{msg} (fetch: {fetch_err})"
            raise LensException(msg)
        if not self._has_upstream():
            hint = f" {push_err}" if push_err else ""
            raise LensException(
                f"push failed: no upstream branch; set upstream on first push (e.g. git push -u).{hint}"
            )
        ahead = self._rev_list_count("HEAD..@{upstream}")
        if ahead > 0:
            raise LensException(
                "cannot push: the remote has commits that are not in this branch yet. "
                "Run `lens refresh` with a clean tree to fast-forward, or `lens refresh --reset` "
                "to match the remote and discard local unpushed commits and uncommitted work. "
                "For merge or rebase, use git on the machine directly."
            )
        if push_err:
            raise LensException(f"push failed: {push_err}")
        raise LensException("push failed")

    def push(self) -> None:
        """Push the current branch to its upstream (requires remote configured)."""
        self.push_or_raise()

    # ------------------------------------------------------------------
    # File write operations — all trigger ownership check on first call
    # ------------------------------------------------------------------

    def write_file(self, path: Path, content: str) -> None:
        self._ensure_ownership()
        if path.is_file() and not content.strip():
            try:
                if not path.read_text(encoding="utf-8").strip():
                    return
            except OSError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.invalidate_normalized_path(path)
        from lens.core.speech.tts_cache_sync import maybe_prune_tts_after_narrative_write

        maybe_prune_tts_after_narrative_write(self._root, path)

    def write_file_bytes(self, path: Path, data: bytes) -> None:
        self._ensure_ownership()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.invalidate_normalized_path(path)

    def delete_file(self, path: Path) -> None:
        self._ensure_ownership()
        if path.exists():
            from lens.core.speech.tts_cache_sync import (
                maybe_remove_tts_cache_before_narrative_delete,
            )

            maybe_remove_tts_cache_before_narrative_delete(self._root, path)
            path.unlink()
        self.invalidate_normalized_path(path)

    def mkdir(self, path: Path) -> None:
        self._ensure_ownership()
        path.mkdir(parents=True, exist_ok=True)

    def rmdir(self, path: Path) -> None:
        self._ensure_ownership()
        if path.exists() and path.is_dir():
            path.rmdir()

    def rename(self, src: Path, dst: Path) -> None:
        self._ensure_ownership()
        from lens.core.speech.tts_cache_sync import maybe_move_tts_cache_on_narrative_rename

        maybe_move_tts_cache_on_narrative_rename(self._root, src, dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        self.invalidate_normalized_path(src)
        self.invalidate_normalized_path(dst)

    def copy_file(self, src: Path, dst: Path) -> None:
        """Copy file content from src to dst. Creates parent dirs if needed."""
        self._ensure_ownership()
        content = src.read_text(encoding="utf-8")
        self.write_file(dst, content)
        self.invalidate_normalized_path(dst)

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
