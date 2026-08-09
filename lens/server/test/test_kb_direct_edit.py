"""Direct KB edits from the UI must not swallow a pending operator preview.

See issue #129: saving a KB item used to run through an ``owner=None`` Storage,
which staged *everything* unstaged — quietly accepting a generation the user had
not reviewed.  Direct user edits now stage only the file they touch.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from lens.core.storage import Storage
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

PREVIEW = "\n[write]: #\nan unreviewed generation\n[/write]: #\n"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    ).stdout


@pytest.fixture()
def kb_project(fake_llm: FakeLLMServer) -> Generator[tuple[TestClient, Path], None, None]:
    """A throwaway project (fresh per test — these tests dirty the git tree)."""
    from lens.server.main import create_app

    tmp = tempfile.mkdtemp(prefix="lens_kb_direct_")
    project_dir = Path(tmp)
    session = setup_test_project(project_dir, fake_llm.base_url)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client, project_dir
    shutil.rmtree(tmp, ignore_errors=True)


def _pending_preview(project_dir: Path) -> Path:
    """Leave an unstaged, unreviewed operator preview on the root node."""
    node = project_dir / "narrative" / "story" / "_node.md"
    node.write_text(node.read_text() + PREVIEW, encoding="utf-8")
    assert "narrative/story/_node.md" in _git(project_dir, "diff", "--name-only")
    return node


class TestKbSaveKeepsPreviewPending:
    def test_save_stages_only_the_kb_file(self, kb_project: tuple[TestClient, Path]) -> None:
        client, project_dir = kb_project
        _pending_preview(project_dir)

        r = client.put("/test/kb/item/person.amy", json={"content": "Amy, hp 4.\n"})
        assert r.status_code == 200

        staged = _git(project_dir, "diff", "--cached", "--name-only").split()
        assert "knowledge/person/amy.md" in staged
        assert "narrative/story/_node.md" not in staged
        assert "narrative/story/_node.md" in _git(project_dir, "diff", "--name-only")

    def test_preview_stays_discardable(self, kb_project: tuple[TestClient, Path]) -> None:
        client, project_dir = kb_project
        node = _pending_preview(project_dir)

        client.put("/test/kb/item/person.amy", json={"content": "Amy, hp 4.\n"})
        Storage(project_dir).rollback()

        assert PREVIEW not in node.read_text()
        assert (project_dir / "knowledge" / "person" / "amy.md").read_text() == "Amy, hp 4.\n"

    def test_burst_of_saves_leaves_preview_alone(
        self, kb_project: tuple[TestClient, Path]
    ) -> None:
        client, project_dir = kb_project
        _pending_preview(project_dir)

        for hp in (9, 8, 7):
            r = client.put("/test/kb/item/person.amy", json={"content": f"hp: {hp}\n"})
            assert r.status_code == 200

        assert "narrative/story/_node.md" in _git(project_dir, "diff", "--name-only")
        assert "knowledge/person/amy.md" not in _git(project_dir, "diff", "--name-only")

    def test_create_stages_only_the_new_item(
        self, kb_project: tuple[TestClient, Path]
    ) -> None:
        client, project_dir = kb_project
        _pending_preview(project_dir)

        r = client.post("/test/kb/items", json={"id": "person.bo", "content": "Bo.\n"})
        assert r.status_code == 200

        staged = _git(project_dir, "diff", "--cached", "--name-only").split()
        assert "knowledge/person/bo.md" in staged
        assert "narrative/story/_node.md" not in staged

    def test_tag_edit_stages_only_tags_file(
        self, kb_project: tuple[TestClient, Path]
    ) -> None:
        client, project_dir = kb_project
        _pending_preview(project_dir)

        r = client.patch("/test/kb/item/person.amy/tags", json={"add": ["wounded"]})
        assert r.status_code == 200
        assert "wounded" in r.json()["tags"]

        staged = _git(project_dir, "diff", "--cached", "--name-only").split()
        assert "knowledge/tags.toml" in staged
        assert "narrative/story/_node.md" not in staged
        # The shared store must not serve a stale tag cache after the write.
        items = client.get("/test/kb/items", params={"type": "person"}).json()
        amy = next(i for i in items if i["id"] == "person.amy")
        assert "wounded" in amy["tags"]

    def test_delete_stages_only_the_deletion(
        self, kb_project: tuple[TestClient, Path]
    ) -> None:
        client, project_dir = kb_project
        _pending_preview(project_dir)

        assert client.delete("/test/kb/item/place.forest").status_code == 200

        staged = _git(project_dir, "diff", "--cached", "--name-only").split()
        assert "knowledge/place/forest.md" in staged
        assert "narrative/story/_node.md" not in staged

    def test_edit_of_a_file_the_transaction_owns_merges_into_it(
        self, kb_project: tuple[TestClient, Path]
    ) -> None:
        """Same-file conflict: don't split the operator's work across the boundary."""
        client, project_dir = kb_project
        _pending_preview(project_dir)
        amy = project_dir / "knowledge" / "person" / "amy.md"
        amy.write_text("hp: 7\n", encoding="utf-8")

        assert client.put("/test/kb/item/person.amy", json={"content": "hp: 4\n"}).status_code == 200

        assert _git(project_dir, "diff", "--cached", "--name-only").strip() == ""
        assert "knowledge/person/amy.md" in _git(project_dir, "diff", "--name-only")

        Storage(project_dir).rollback()
        assert amy.read_text() != "hp: 4\n"
