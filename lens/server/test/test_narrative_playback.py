"""Visual-novel playback routes: JSON manifest + TTS SSE."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    (root / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)


@pytest.fixture
def vn_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    _git_init(tmp_path)
    (tmp_path / "lens.toml").write_text(
        '[project]\nnarrative = "story"\nmount_point = "media"\n'
    )
    media = tmp_path / "media"
    media.mkdir()
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(
        "Line one.\n\n![hero](hero.png)\n\nLine two.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "n"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


def _parse_sse_data_lines(text: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_playback_manifest_order_and_shape(vn_client: TestClient) -> None:
    r = vn_client.get("/test/narrative/node/story/playback")
    assert r.status_code == 200
    data = r.json()
    assert data["address"] == "story"
    assert data["tts_enabled"] is False
    items = data["items"]
    assert len(items) == 3
    assert items[0]["type"] == "text"
    assert items[0]["text"] == "Line one."
    assert "tts_cached" not in items[0]
    assert items[1]["type"] == "image"
    assert items[1]["url"] == "hero.png"
    assert items[2]["type"] == "text"
    assert items[2]["text"] == "Line two."


def test_playback_manifest_includes_chat_session_labels_for_chat_node(tmp_path: Path) -> None:
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    _git_init(tmp_path)
    (tmp_path / "lens.toml").write_text(
        '[project]\nnarrative = "story"\nmount_point = "media"\n'
    )
    (tmp_path / "media").mkdir()
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(
        "# story\n\n[chat:chat-bob-alice\n"
        "    as_kb_id: npc.bob-the-smith\n"
        "    with_kb_id: human.alice_jones\n"
        "]: #\n",
        encoding="utf-8",
    )
    chat_dir = narrative_dir / "chat-bob-alice"
    chat_dir.mkdir()
    (chat_dir / "_node.md").write_text("Hello there.\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "chat"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        r = client.get("/test/narrative/node/story/chat-bob-alice/playback")

    assert r.status_code == 200
    data = r.json()
    assert data["chat_session"] == {
        "ai_label": "Bob The Smith",
        "human_label": "Alice Jones",
    }
    assert data["items"][0]["text"] == "Hello there."


def test_playback_manifest_includes_attach_video_embed(tmp_path: Path) -> None:
    from lens.core.commands.attach import build_embed
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    _git_init(tmp_path)
    (tmp_path / "lens.toml").write_text(
        '[project]\nnarrative = "story"\nmount_point = "media"\n'
    )
    (tmp_path / "media").mkdir()
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    embed = build_embed("bg.mp4", ".mp4")
    (narrative_dir / "_node.md").write_text(
        f"Lead.\n\n{embed}\n\nTail.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "n"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        r = client.get("/test/narrative/node/story/playback")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3
    assert items[0]["type"] == "text"
    assert items[0]["text"] == "Lead."
    assert items[1]["type"] == "video"
    assert items[1]["url"] == "bg.mp4"
    assert items[1]["alt"] == "bg.mp4"
    assert items[2]["type"] == "text"
    assert items[2]["text"] == "Tail."


def test_playback_adds_tts_front_matter_before_chunking_when_speech_ready(
    vn_client: TestClient, tmp_path: Path
) -> None:
    """``tts_cached`` is written on first GET when mount + speech are ready so ``line`` stays valid."""
    with mock.patch(
        "lens.server.routes.narrative_playback.speech_registry.is_speech_backend_ready",
        return_value=True,
    ):
        r = vn_client.get("/test/narrative/node/story/playback")
    assert r.status_code == 200
    data = r.json()
    assert data["tts_enabled"] is True
    node_path = tmp_path / "narrative" / "story" / "_node.md"
    body = node_path.read_text(encoding="utf-8")
    assert "tts_cached" in body
    items = data["items"]
    assert items[0]["type"] == "text"
    assert items[0]["text"] == "Line one."
    assert items[0]["line"] > 1
    assert items[0]["tts_cached"] is False


def test_tts_sse_sets_tts_cached_and_writes_mp3(vn_client: TestClient, tmp_path: Path) -> None:
    first = vn_client.get("/test/narrative/node/story/playback").json()
    one = first["items"][0]
    assert one["type"] == "text"
    line = one["line"]
    chunk_id = one["id"]
    fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 64

    with mock.patch(
        "lens.core.commands.media_tts.synthesize_speech_bytes",
        return_value=fake_mp3,
    ):
        r = vn_client.get(
            "/test/narrative/node/story/tts",
            params={"line": line, "chunk_id": chunk_id},
        )
    assert r.status_code == 200
    events = _parse_sse_data_lines(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "done"
    assert "audio" in types
    start = events[0]
    assert start["from_cache"] is False
    assert start["content_type"] == "audio/mpeg"

    node_path = tmp_path / "narrative" / "story" / "_node.md"
    body = node_path.read_text(encoding="utf-8")
    assert "tts_cached" in body

    from lens.core.narrative import NarrativeNode
    from lens.core.speech.chunks import tts_cache_mount_prefix

    narrative_root = tmp_path / "narrative" / "story"
    node = NarrativeNode(narrative_root=narrative_root, key_path=())
    p = tmp_path / "media"
    for part in tts_cache_mount_prefix(node).split("/"):
        p = p / part
    mp3 = p / f"{chunk_id}.mp3"
    assert mp3.is_file()
    assert mp3.read_bytes() == fake_mp3


def test_tts_unknown_chunk_returns_404(vn_client: TestClient) -> None:
    r = vn_client.get(
        "/test/narrative/node/story/tts",
        params={"line": 1, "chunk_id": "chk-nonexistent"},
    )
    assert r.status_code == 404
    assert "no TTS chunk" in r.json()["detail"]


def test_tts_post_render_ready_when_cached(vn_client: TestClient, tmp_path: Path) -> None:
    first = vn_client.get("/test/narrative/node/story/playback").json()
    one = first["items"][0]
    line, chunk_id = one["line"], one["id"]
    fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 64
    with mock.patch(
        "lens.core.commands.media_tts.synthesize_speech_bytes",
        return_value=fake_mp3,
    ):
        vn_client.get(
            "/test/narrative/node/story/tts",
            params={"line": line, "chunk_id": chunk_id},
        )
        after = vn_client.get("/test/narrative/node/story/playback").json()
        one2 = after["items"][0]
        r = vn_client.post(
            "/test/narrative/node/story/tts/render",
            params={"line": one2["line"], "chunk_id": one2["id"]},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_tts_prefetch_and_stream_share_one_synthesis(vn_client: TestClient) -> None:
    import time

    first = vn_client.get("/test/narrative/node/story/playback").json()
    one = first["items"][0]
    line, chunk_id = one["line"], one["id"]
    fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 64

    def slow_synth(*_a: object, **_kw: object) -> bytes:
        time.sleep(0.2)
        return fake_mp3

    with mock.patch(
        "lens.core.commands.media_tts.synthesize_speech_bytes",
        side_effect=slow_synth,
    ) as m:
        r0 = vn_client.post(
            "/test/narrative/node/story/tts/render",
            params={"line": line, "chunk_id": chunk_id},
        )
        assert r0.status_code == 202
        assert r0.json()["status"] == "started"
        r1 = vn_client.post(
            "/test/narrative/node/story/tts/render",
            params={"line": line, "chunk_id": chunk_id},
        )
        assert r1.status_code == 202
        assert r1.json()["status"] == "rendering"
        r2 = vn_client.get(
            "/test/narrative/node/story/tts",
            params={"line": line, "chunk_id": chunk_id},
        )
    assert r2.status_code == 200
    events = _parse_sse_data_lines(r2.text)
    assert events[-1]["type"] == "done"
    assert m.call_count == 1
