"""KB routes report where each item resolves from, so the UI can show it.

The KB browser is the one place a person edits dataset material by hand. Without
a source on the response, "this is bundled, saving it forks a project copy" is
information the UI simply does not have.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project


@pytest.fixture()
def kb_client(fake_llm: FakeLLMServer) -> Generator[TestClient, None, None]:
    from lens.server.main import create_app

    tmp = tempfile.mkdtemp(prefix="lens_kb_source_")
    session = setup_test_project(Path(tmp), fake_llm.base_url, dataset="testing")
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client
    shutil.rmtree(tmp, ignore_errors=True)


def _item(client: TestClient, id_: str) -> dict[str, Any]:
    r = client.get(f"/test/kb/item/{id_}")
    assert r.status_code == 200, r.text
    return r.json()


class TestItemDetailSource:
    def test_a_dataset_item_names_its_dataset(self, kb_client: TestClient) -> None:
        source = _item(kb_client, "person.hero")["source"]

        assert source["kind"] == "dataset"
        assert source["dataset"] == "testing"
        assert source["label"] == "dataset:testing"
        assert source["shadows"] == []

    def test_a_project_item_reports_the_project(self, kb_client: TestClient) -> None:
        r = kb_client.post("/test/kb/items", json={"id": "place.nyc", "content": "NYC\n"})
        assert r.status_code == 200, r.text

        source = _item(kb_client, "place.nyc")["source"]

        assert source["kind"] == "project"
        assert source["label"] == "project"

    def test_saving_a_dataset_item_makes_it_a_project_fork(
        self, kb_client: TestClient
    ) -> None:
        """The copy-on-write moment: same id, different answer afterwards."""
        assert _item(kb_client, "person.hero")["source"]["kind"] == "dataset"

        r = kb_client.put("/test/kb/item/person.hero", json={"content": "My hero.\n"})
        assert r.status_code == 200, r.text

        source = _item(kb_client, "person.hero")["source"]
        assert source["kind"] == "project"
        assert source["shadows"] == ["testing"]
        assert source["label"] == "project (shadows dataset:testing)"


class TestItemListSource:
    def test_the_listing_labels_every_item(self, kb_client: TestClient) -> None:
        r = kb_client.get("/test/kb/items?type=person")
        assert r.status_code == 200, r.text
        items = r.json()

        assert items
        by_id = {item["id"]: item for item in items}
        assert by_id["person.hero"]["source"]["label"] == "dataset:testing"
        for item in items:
            assert item["source"] is not None, item["id"]
