"""Server side of triggers (#195): node/stats offers and the ``trigger`` body field.

The UI fires a trigger the way the CLI does: it submits the stored ``run`` as an
ordinary command line, with ``trigger`` added so the session is ``<slug>-tr``.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Enso opens the store cellar hatch\n"
    "        run: design\n"
    "      design-loft:\n"
    "        when: Enso climbs to the loft\n"
    "        run: design\n"
    "]: #\n"
    "\n"
    "The village store.\n"
)


@pytest.fixture()
def client(fake_llm: FakeLLMServer, tmp_path: Path) -> Generator[TestClient, None, None]:
    from lens.core.pinning import pin
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = setup_test_project(tmp_path, fake_llm.base_url, opening_write=False)
    (tmp_path / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge" / "prep" / "store.md").write_text(PREP)
    narrative = session.active_narrative
    assert narrative is not None
    storage = session.new_storage()
    pin(narrative, ["prep.store"], storage)
    md = narrative.md_path()
    md.write_text(md.read_text().rstrip("\n") + "\n\n<!-- suggest:design-cellar -->\n")
    storage.stage_all()
    app = create_app({"test": ProjectSession(tmp_path, tmp_path)})
    with TestClient(app) as c:
        yield c


def test_cursor_node_and_stats_carry_offers(client: TestClient) -> None:
    node = client.get("/test/narrative/node/story").json()
    assert [o["slug"] for o in node["offers"]] == ["design-cellar"]
    assert node["offers"][0]["when"] == "Enso opens the store cellar hatch"
    assert node["offers"][0]["declared_on"] == "prep.store"
    stats = client.get("/test/stats").json()
    assert [o["slug"] for o in stats["offers_at_cursor"]] == ["design-cellar"]


def test_design_body_trigger_field_passes_through(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/test/operator/design", json={"trigger": "design-loft"})
    assert r.status_code == 200
    assert (tmp_path / "narrative" / "story" / "design-loft-tr.md").exists()


def test_design_body_refuses_a_done_trigger(client: TestClient) -> None:
    first = client.post("/test/operator/design", json={"trigger": "design-cellar"})
    assert first.status_code == 200
    again = client.post("/test/operator/design", json={"trigger": "design-cellar"})
    assert "already done" in again.text


def test_design_body_refuses_another_operators_trigger(client: TestClient) -> None:
    r = client.post("/test/operator/design", json={"trigger": "play-cellar"})
    assert "does not run design" in r.text


def test_design_body_module_ids_like_the_cli(client: TestClient, tmp_path: Path) -> None:
    from lens.core.annotations import parse_annotations

    r = client.post(
        "/test/operator/design",
        json={"trigger": "design-loft", "module_ids": ["person"], "prompt": "build the loft"},
    )
    assert r.status_code == 200, r.text
    root = (tmp_path / "narrative" / "story" / "_node.md").read_text()
    opened = [a for a in parse_annotations(root) if a.id == "design-loft-tr" and not a.closing]
    assert len(opened) == 1
    assert opened[0].params["module"] == "person"
    assert opened[0].params["trigger"] == "design-loft"


def test_test_play_trigger_rehearses_and_writes_nothing(fake_llm: FakeLLMServer, tmp_path: Path) -> None:
    import json
    import subprocess

    from lens.core.pinning import pin
    from lens.core.project import ProjectSession
    from lens.server.main import create_app
    from lens.testing.fake_llm import REPLY_TRIGGER
    from lens.testing.regression_fixtures import setup_rpg_play_pins

    session = setup_rpg_play_pins(tmp_path, fake_llm.base_url)
    (tmp_path / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge" / "prep" / "store.md").write_text(PREP)
    narrative = session.active_narrative
    assert narrative is not None
    storage = session.new_storage()
    pin(narrative, ["prep.store"], storage)
    storage.stage_all()
    subprocess.run(["git", "commit", "-qm", "prep"], cwd=tmp_path, check=True)
    app = create_app({"test": ProjectSession(tmp_path, tmp_path)})
    cue = f"I open the hatch. {REPLY_TRIGGER} {json.dumps('Up.\\n<!-- suggest:design-cellar -->')}"
    with TestClient(app) as c:
        r = c.post(
            "/test/operator/test-play",
            json={
                "trigger": "design-cellar",
                "targets": ["prep.store"],
                "at": "Night, at the hatch",
                "prompt": cue,
                "repeat": 2,
            },
        )
        assert r.status_code == 200
        done = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ") and '"done"' in line]
        assert done
        rehearsal = done[-1]["rehearsal"]
        assert rehearsal["hits"] == 2
        assert rehearsal["targets"] == ["prep.store"]
        assert rehearsal["at"] == "Night, at the hatch"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True)
    assert status.stdout == ""
