"""SSE operator routes: regression tests for play and stream error handling."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lens.core.operator import OperatorError


def _git_init(project: Path) -> None:
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    (project / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=project,
        capture_output=True,
        check=True,
    )


@pytest.fixture
def rpg_play_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Lens project with ``rpg`` dataset and a pinned ``pc.*`` for play."""
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    _git_init(tmp_path)
    (tmp_path / "lens.toml").write_text(
        '[project]\nnarrative = "story"\ndatasets = ["rpg"]\n'
        '[[llm]]\nbase_url = "https://example.invalid/v1"\nmodel = "test"\n'
    )
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(
        "[\n  kb_pin:\n    - pc.bob\n]: #\n\n# test\n"
    )
    pc_dir = tmp_path / "knowledge" / "pc"
    pc_dir.mkdir(parents=True)
    (pc_dir / "bob.md").write_text("Bob\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


def _drain_sse_events(client: TestClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with client.stream("POST", url, json=body) as response:
        assert response.status_code == 200, response.text
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _play_session_md(project_root: Path) -> str:
    story = project_root / "narrative" / "story"
    play_files = sorted(
        p for p in story.iterdir() if p.is_file() and p.name.startswith("play-") and p.suffix == ".md"
    )
    assert len(play_files) == 1, play_files
    return play_files[0].read_text(encoding="utf-8")


class TestPlayOperatorStream:
    def test_pass_only_after_player_turn_succeeds(self, rpg_play_client: TestClient, tmp_path: Path) -> None:
        async def _gm(*_a: Any, **_k: Any) -> str:
            return "GM line.\n"

        with patch("lens.core.operator.generate_text", _gm):
            ev1 = _drain_sse_events(
                rpg_play_client,
                "/test/operator/play",
                {"prompt": "I enter", "do_pass": True, "pins": [], "unpins": []},
            )
            assert any(e.get("type") == "done" for e in ev1)
            assert any(
                e.get("type") == "progress" and e.get("phase") == "operator_started"
                for e in ev1
            )

        with patch("lens.core.operator.generate_text", _gm):
            ev2 = _drain_sse_events(
                rpg_play_client,
                "/test/operator/play",
                {"prompt": "I wait", "pins": [], "unpins": []},
            )
            assert any(e.get("type") == "done" for e in ev2)

        with patch("lens.core.operator.generate_text", _gm):
            ev3 = _drain_sse_events(
                rpg_play_client,
                "/test/operator/play",
                {"prompt": None, "do_pass": True, "pins": [], "unpins": []},
            )
            assert any(e.get("type") == "done" for e in ev3)

        text = _play_session_md(tmp_path)
        assert "> [Player] I enter" in text
        assert "> [Player] I wait" in text
        assert text.count("[/play") >= 2

    def test_operator_error_keeps_player_line_and_explains(self, rpg_play_client: TestClient, tmp_path: Path) -> None:
        calls = {"n": 0}

        async def _gm(*_a: Any, **_k: Any) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return "First GM.\n"
            raise OperatorError("forced failure")

        with patch("lens.core.operator.generate_text", _gm):
            ev1 = _drain_sse_events(
                rpg_play_client,
                "/test/operator/play",
                {"prompt": "setup", "do_pass": True, "pins": [], "unpins": []},
            )
            assert any(e.get("type") == "done" for e in ev1)

        marker = "KEPT_AFTER_GM_FAIL"
        with patch("lens.core.operator.generate_text", _gm):
            ev2 = _drain_sse_events(
                rpg_play_client,
                "/test/operator/play",
                {"prompt": marker, "do_pass": True, "pins": [], "unpins": []},
            )
        assert any(e.get("type") == "error" for e in ev2)
        assert not any(e.get("type") == "done" for e in ev2)
        err_events = [e for e in ev2 if e.get("type") == "error"]
        assert any("player line was saved" in (e.get("message") or "").lower() for e in err_events)

        text = _play_session_md(tmp_path)
        assert marker in text
        assert "> [Player] setup" in text
