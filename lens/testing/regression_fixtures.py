"""Shared regression fixture setup for e2e CLI, API, and sandbox tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib
import tomli_w

from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.testing.project import setup_test_project


def _git(project_dir: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project_dir, capture_output=True, check=True)

if TYPE_CHECKING:
    pass

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _clear_kb_registry() -> None:
    KnowledgeStore.clear_registry()
    MediaService.clear_registry()


def _write_lens_toml(
    project_dir: Path, llm_base_url: str, *, extra: dict[str, object] | None = None
) -> None:
    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["llm"] = [{"id": "mock", "base_url": llm_base_url, "model": "mock-model"}]
    if extra:
        cfg.update(extra)
    with open(lens_toml, "wb") as fh:
        tomli_w.dump(cfg, fh)


def _run_setup_script(project_dir: Path, script_name: str) -> None:
    script = _REPO_ROOT / "e2e" / "fixtures" / script_name / "setup.sh"
    if not script.is_file():
        raise FileNotFoundError(script)
    env = {**os.environ, "PROJECT": str(project_dir)}
    subprocess.run(["bash", str(script)], cwd=_REPO_ROOT, env=env, check=True, capture_output=True)
    _clear_kb_registry()


def setup_auto_compress_low_threshold(
    project_dir: Path,
    llm_base_url: str,
    *,
    narrative_name: str = "story",
) -> ProjectSession:
    """Project with low compress thresholds and prose above *m* so auto-compress can fire."""
    session = setup_test_project(
        project_dir,
        llm_base_url,
        narrative_name=narrative_name,
    )
    _write_lens_toml(
        project_dir,
        llm_base_url,
        extra={
            "compress": {
                "sm": 50,
                "m": 100,
                "l": 500,
                "xl": 1000,
                "auto_compress": True,
            },
        },
    )
    narrative = session.active_narrative
    assert narrative is not None
    cursor = narrative.find_cursor()
    filler = "Bench prose line for auto-compress threshold testing.\n" * 12
    cursor.md_path().write_text(f"# story\n\n{filler}", encoding="utf-8")
    Storage(project_dir).stage_all()
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-m", "fixture: auto_compress seed")
    _clear_kb_registry()
    return session


def setup_auto_compress_disabled_node(
    project_dir: Path,
    llm_base_url: str,
) -> ProjectSession:
    """Large node with per-node ``compress.auto_compress: false``."""
    session = setup_auto_compress_low_threshold(project_dir, llm_base_url)
    narrative = session.active_narrative
    assert narrative is not None
    cursor = narrative.find_cursor()
    text = cursor.md_path().read_text(encoding="utf-8")
    fm = "[\n    compress:\n        auto_compress: false\n]: #\n\n"
    cursor.md_path().write_text(fm + text, encoding="utf-8")
    Storage(project_dir).stage_all()
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-m", "fixture: auto_compress disabled on node")
    _clear_kb_registry()
    return session


def setup_remember_section(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """Remember-at-section-close fixture (mirrors bench/scenarios/remember_section_setup.sh)."""
    setup_test_project(
        project_dir,
        llm_base_url,
        narrative_name="default",
        opening_write=False,
    )
    _run_setup_script(project_dir, "remember_section")
    _clear_kb_registry()
    return ProjectSession(project_dir, project_dir)


def setup_workflow_write_long(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """Root node with visible bytes above default *sm* but default compress *m* (no auto trigger)."""
    session = setup_test_project(project_dir, llm_base_url)
    narrative = session.active_narrative
    assert narrative is not None
    cursor = narrative.find_cursor()
    filler = "Long prose for workflow UI sandbox.\n" * 400
    cursor.md_path().write_text(f"# story\n\n{filler}", encoding="utf-8")
    Storage(project_dir).stage_all()
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-m", "fixture: workflow_write_long")
    _clear_kb_registry()
    return session


def setup_advance_minimal(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """Advance-fronts subset for CLI regression (AC-16): timeline + fronts, no bench shell."""
    from lens.core.commands.kb import kb_add, kb_tag

    session = setup_test_project(
        project_dir,
        llm_base_url,
        datasets=["rpg", "testing"],
        narrative_name="default",
        opening_write=False,
    )
    orig_cwd = Path.cwd()
    os.chdir(project_dir)
    try:
        kb_add(
            "timeline.vale",
            "# The Thornvale Chronicle\n\n- Started: 3rd of Ashmonth\n- Day: 1\n",
            False,
        )
        kb_add("front.blight", "# The Spreading Blight\n\n- Problem: fungal rot\n", False)
        kb_tag("front.blight", ["timeline.vale"], [])
        narrative = session.active_narrative
        assert narrative is not None
        text = (
            "[\n  kb_pin:\n    - timeline.vale\n]: #\n\n# default\n\n"
            "Camp at the mill pond.\n"
        )
        narrative.find_cursor().md_path().write_text(text, encoding="utf-8")
        Storage(project_dir).stage_all()
        _git(project_dir, "add", "-A")
        _git(project_dir, "commit", "-m", "fixture: advance_minimal")
    finally:
        os.chdir(orig_cwd)
    _clear_kb_registry()
    return session


_COMPOSITE_MEDIA_ASSETS_DIR = _REPO_ROOT / "e2e" / "assets" / "composite_media"
_COMPOSITE_MEDIA_ASSET_NAMES = (
    "test_bg.jpg",
    "test_bg.jpg.yml",
    "test_bg_wide.jpg",
    "test_bg_wide.jpg.yml",
    "test_fg.png",
    "test_fg.png.yml",
)


def setup_composite_media_project(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """Project with a media mount + two bg/fg composite scenes (issue #99 layered rendering).

    Reuses three real photos (``e2e/assets/composite_media/``) in two pairings so both
    orientation-mismatch directions are covered without needing extra binary fixtures:

    * ``vn-combo-a``: landscape bg (``test_bg_wide.jpg``) + portrait fg (``test_fg.png``)
    * ``vn-combo-b``: portrait bg (``test_bg.jpg``) + landscape fg (``test_bg_wide.jpg`` reused —
      its ``composite: background`` sidecar is irrelevant here since the embed line is written
      directly rather than through the metadata-driven carousel pairing flow)
    """
    from lens.core.commands.attach import build_layered_embed

    setup_test_project(project_dir, llm_base_url, narrative_name="story")

    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["project"]["mount_point"] = "media"
    with open(lens_toml, "wb") as fh:
        tomli_w.dump(cfg, fh)

    media_dir = project_dir / "media"
    media_dir.mkdir(exist_ok=True)
    for name in _COMPOSITE_MEDIA_ASSET_NAMES:
        shutil.copy(_COMPOSITE_MEDIA_ASSETS_DIR / name, media_dir / name)

    # Content is *only* the composite embed line (no heading/prose) so it is
    # unambiguously the first (and only) VN playback item — vn_i=0 always lands
    # on the layered scene, with no dependency on TTS text-chunking behavior.
    narrative_dir = project_dir / "narrative" / "story"
    combo_a = build_layered_embed("test_bg_wide.jpg", "test_fg.png")
    combo_b = build_layered_embed("test_bg.jpg", "test_bg_wide.jpg")
    (narrative_dir / "vn-combo-a.md").write_text(f"{combo_a}\n", encoding="utf-8")
    (narrative_dir / "vn-combo-b.md").write_text(f"{combo_b}\n", encoding="utf-8")

    Storage(project_dir).stage_all()
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-m", "fixture: composite_media")
    _clear_kb_registry()
    return ProjectSession(project_dir, project_dir)


def setup_media_attach_project(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """Media mount + one anchor with two same-facet foreground variants (issue #51).

    Reuses ``test_fg.png``/``test_bg.jpg`` (``e2e/assets/composite_media/``) under new
    names so the ``amy!`` anchor has an undecided ``emotion`` facet (happy vs sad) to
    classify. The root node is seeded with one composite attachment (``bg.jpg`` +
    ``amy_happy.png``) — the modality needs an existing composite to build a
    foreground-only pick on top of (issue #51, "composition awareness") — plus front
    matter enabling ``media_attach`` with that anchor.
    """
    from lens.core.commands.attach import build_layered_embed
    from lens.core.pinning import set_media_attach, set_modality

    session = setup_test_project(
        project_dir, llm_base_url, narrative_name="story", opening_write=False
    )

    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["project"]["mount_point"] = "media"
    with open(lens_toml, "wb") as fh:
        tomli_w.dump(cfg, fh)

    media_dir = project_dir / "media"
    media_dir.mkdir(exist_ok=True)
    shutil.copy(_COMPOSITE_MEDIA_ASSETS_DIR / "test_bg.jpg", media_dir / "bg.jpg")
    shutil.copy(_COMPOSITE_MEDIA_ASSETS_DIR / "test_fg.png", media_dir / "amy_happy.png")
    shutil.copy(_COMPOSITE_MEDIA_ASSETS_DIR / "test_fg.png", media_dir / "amy_sad.png")
    (media_dir / "amy_happy.png.yml").write_text(
        "composite: foreground\nfacets:\n  emotion: happy\n", encoding="utf-8"
    )
    (media_dir / "amy_sad.png.yml").write_text(
        "composite: foreground\nfacets:\n  emotion: sad\n", encoding="utf-8"
    )

    orig_cwd = Path.cwd()
    os.chdir(project_dir)
    try:
        narrative = session.active_narrative
        assert narrative is not None
        storage = session.new_storage(owner=None)
        set_media_attach(narrative, "anchor", "amy!", storage)
        set_modality(narrative, "media_attach", True, storage)

        node_path = narrative.md_path()
        seed_embed = build_layered_embed("bg.jpg", "amy_happy.png")
        current = node_path.read_text(encoding="utf-8")
        storage.write_file(node_path, current.rstrip("\n") + f"\n\n{seed_embed}\n")
    finally:
        os.chdir(orig_cwd)

    Storage(project_dir).stage_all()
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-m", "fixture: media_attach")
    _clear_kb_registry()
    return ProjectSession(project_dir, project_dir)


def setup_rpg_play_pins(project_dir: Path, llm_base_url: str) -> ProjectSession:
    """RPG dataset + pc pin for play regression (AC-13 / SH-05)."""
    from lens.core.commands.kb import kb_add
    from lens.core.commands.pin import pin_add

    session = setup_test_project(
        project_dir,
        llm_base_url,
        datasets=["rpg", "testing"],
        narrative_name="default",
        opening_write=False,
    )
    orig_cwd = Path.cwd()
    os.chdir(project_dir)
    try:
        kb_add("pc.elena", "Elena: cautious scout, speaks in short sentences.", False)
        pin_add(session, "pc.elena", None, [], None)
        narrative = session.active_narrative
        assert narrative is not None
        narrative.find_cursor().md_path().write_text(
            "[\n  kb_pin:\n    - pc.elena\n    - rules.rpg\n    - rules.system\n]: #\n\n"
            "# default\n\nAt the forest edge.\n",
            encoding="utf-8",
        )
        Storage(project_dir).stage_all()
        _git(project_dir, "add", "-A")
        _git(project_dir, "commit", "-m", "fixture: rpg_play_pins")
    finally:
        os.chdir(orig_cwd)
    _clear_kb_registry()
    return session
