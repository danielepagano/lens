"""Unit tests for lens.core.commands.diff.parse_unified_diff."""

from __future__ import annotations

from lens.core.commands.diff import parse_unified_diff


class TestParseUnifiedDiffEmpty:
    def test_empty_string(self) -> None:
        assert parse_unified_diff("") == []

    def test_whitespace_only(self) -> None:
        assert parse_unified_diff("   \n  \n") == []


class TestParseUnifiedDiffSingleFile:
    _WRITE_DIFF = """\
diff --git a/narrative/main/ch1.md b/narrative/main/ch1.md
index abc1234..def5678 100644
--- a/narrative/main/ch1.md
+++ b/narrative/main/ch1.md
@@ -10,3 +10,6 @@
 Last context line
+[write:abc123]: #
+Generated story content.
+[/write:abc123]: #
"""

    def test_one_file_returned(self) -> None:
        files = parse_unified_diff(self._WRITE_DIFF)
        assert len(files) == 1

    def test_file_path(self) -> None:
        files = parse_unified_diff(self._WRITE_DIFF)
        assert files[0].path == "narrative/main/ch1.md"

    def test_hunk_count(self) -> None:
        files = parse_unified_diff(self._WRITE_DIFF)
        assert len(files[0].hunks) == 1

    def test_hunk_line_numbers(self) -> None:
        hunk = parse_unified_diff(self._WRITE_DIFF)[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10

    def test_context_lines_included(self) -> None:
        lines = parse_unified_diff(self._WRITE_DIFF)[0].hunks[0].lines
        # Context line is now included for accurate line number tracking
        assert len(lines) == 4
        assert lines[0].kind == "context"
        assert lines[0].text == "Last context line"
        assert all(ln.kind == "add" for ln in lines[1:])

    def test_annotation_flags(self) -> None:
        lines = parse_unified_diff(self._WRITE_DIFF)[0].hunks[0].lines
        # First line is context (not annotation), then add lines
        assert [ln.is_annotation for ln in lines] == [False, True, False, True]

    def test_text_content(self) -> None:
        lines = parse_unified_diff(self._WRITE_DIFF)[0].hunks[0].lines
        assert lines[0].text == "Last context line"
        assert lines[1].text == "[write:abc123]: #"
        assert lines[2].text == "Generated story content."
        assert lines[3].text == "[/write:abc123]: #"


class TestParseUnifiedDiffMultiLineAnnotation:
    """Multi-line annotation opener + YAML params + closing `]: #`."""

    _DIFF = """\
diff --git a/narrative/main/ch1.md b/narrative/main/ch1.md
index abc1234..def5678 100644
--- a/narrative/main/ch1.md
+++ b/narrative/main/ch1.md
@@ -5,3 +5,5 @@
+[write
+  prompt: continue the story
+]: #
+Generated content here.
+[/write:abc123]: #
"""

    def test_annotation_flags(self) -> None:
        lines = parse_unified_diff(self._DIFF)[0].hunks[0].lines
        assert [ln.is_annotation for ln in lines] == [True, True, True, False, True]

    def test_opener_is_annotation(self) -> None:
        lines = parse_unified_diff(self._DIFF)[0].hunks[0].lines
        assert lines[0].text == "[write"
        assert lines[0].is_annotation is True

    def test_param_line_is_annotation(self) -> None:
        lines = parse_unified_diff(self._DIFF)[0].hunks[0].lines
        assert lines[1].text == "  prompt: continue the story"
        assert lines[1].is_annotation is True

    def test_closing_bracket_is_annotation(self) -> None:
        lines = parse_unified_diff(self._DIFF)[0].hunks[0].lines
        assert lines[2].text == "]: #"
        assert lines[2].is_annotation is True


class TestParseUnifiedDiffMutation:
    _EDIT_DIFF = """\
diff --git a/narrative/main/ch1.md b/narrative/main/ch1.md
index abc1234..def5678 100644
--- a/narrative/main/ch1.md
+++ b/narrative/main/ch1.md
@@ -5,6 +5,4 @@
-[edit:abc123
-  prompt: replace
-]: #
-Original line of prose.
-[/edit:abc123]: #
+Proposed replacement prose.
"""

    def test_remove_annotation_flags(self) -> None:
        lines = parse_unified_diff(self._EDIT_DIFF)[0].hunks[0].lines
        remove_lines = [ln for ln in lines if ln.kind == "remove"]
        assert [ln.is_annotation for ln in remove_lines] == [True, True, True, False, True]

    def test_add_content_not_annotation(self) -> None:
        lines = parse_unified_diff(self._EDIT_DIFF)[0].hunks[0].lines
        add_lines = [ln for ln in lines if ln.kind == "add"]
        assert len(add_lines) == 1
        assert add_lines[0].is_annotation is False

    def test_hunk_line_numbers(self) -> None:
        hunk = parse_unified_diff(self._EDIT_DIFF)[0].hunks[0]
        assert hunk.old_start == 5
        assert hunk.new_start == 5


class TestParseUnifiedDiffMultiFile:
    _MULTI_DIFF = """\
diff --git a/narrative/main/a.md b/narrative/main/a.md
index 000000..111111 100644
--- a/narrative/main/a.md
+++ b/narrative/main/a.md
@@ -1,1 +1,2 @@
 context
+added line
diff --git a/narrative/main/b.md b/narrative/main/b.md
index 222222..333333 100644
--- a/narrative/main/b.md
+++ b/narrative/main/b.md
@@ -3,1 +3,1 @@
-old line
+new line
"""

    def test_two_files(self) -> None:
        files = parse_unified_diff(self._MULTI_DIFF)
        assert len(files) == 2

    def test_file_paths(self) -> None:
        files = parse_unified_diff(self._MULTI_DIFF)
        assert files[0].path == "narrative/main/a.md"
        assert files[1].path == "narrative/main/b.md"

    def test_second_file_hunk_numbers(self) -> None:
        hunk = parse_unified_diff(self._MULTI_DIFF)[1].hunks[0]
        assert hunk.old_start == 3
        assert hunk.new_start == 3


class TestParseUnifiedDiffNewFile:
    """Untracked new file via git diff --no-index /dev/null <file>."""

    _NEW_FILE_DIFF = """\
diff --git a/dev/null b/narrative/main/new.md
new file mode 100644
index 0000000..abcdef1
--- /dev/null
+++ b/narrative/main/new.md
@@ -0,0 +1,3 @@
+[write:xyz]: #
+Brand new content.
+[/write:xyz]: #
"""

    def test_new_file_path(self) -> None:
        files = parse_unified_diff(self._NEW_FILE_DIFF)
        assert len(files) == 1
        assert files[0].path == "narrative/main/new.md"

    def test_all_add_lines(self) -> None:
        lines = parse_unified_diff(self._NEW_FILE_DIFF)[0].hunks[0].lines
        assert all(ln.kind == "add" for ln in lines)

    def test_annotation_detection(self) -> None:
        lines = parse_unified_diff(self._NEW_FILE_DIFF)[0].hunks[0].lines
        assert [ln.is_annotation for ln in lines] == [True, False, True]
