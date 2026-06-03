"""TTS cache on the media mount: prune orphans, remove/move subtrees, collate migration."""

from __future__ import annotations

from pathlib import Path

from lens.core.annotations import parse_front_matter
from lens.core.narrative import NarrativeNode
from lens.core.pinning import TTS_CACHED, set_tts_cached_rev
from lens.core.project import ProjectSession, get_mount_backend, has_mount_config
from lens.core.speech.chunks import TTS_CHUNK_REVISION, chunks_for_node_text, tts_cache_mount_prefix


def text_has_tts_cached(raw_md: str) -> bool:
    return bool(parse_front_matter(raw_md).get(TTS_CACHED))


def node_uses_tts_cache(node: NarrativeNode) -> bool:
    return text_has_tts_cached(node.md_path().read_text(encoding="utf-8"))


def ensure_tts_front_matter_for_line_stability(
    session: ProjectSession,
    node: NarrativeNode,
) -> None:
    """Pin ``tts_cached`` before chunking when a mount exists so line numbers stay stable.

    Must run before playback manifests or TTS routes return ``line`` values. Synthesis must not
    be the first writer of front matter while clients hold stale line numbers from playback.
    """
    if not has_mount_config(session.project_root):
        return
    if node_uses_tts_cache(node):
        return
    storage = session.new_storage(owner=None)
    set_tts_cached_rev(node, TTS_CHUNK_REVISION, storage)


def narrative_storage_path_to_node(git_root: Path, path: Path) -> NarrativeNode | None:
    """Map a narrative markdown file or folder-node directory to :class:`NarrativeNode`."""
    try:
        resolved = path.resolve()
        root = git_root.resolve()
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[0] != "narrative":
        return None
    slug = parts[1]
    narrative_root = root / "narrative" / slug
    rest = parts[2:]
    if not rest:
        return None
    if resolved.is_dir():
        if not (resolved / "_node.md").is_file():
            return None
        return NarrativeNode(narrative_root=narrative_root, key_path=tuple(rest))
    name = rest[-1]
    prefix = rest[:-1]
    if name == "_node.md":
        key_path: tuple[str, ...] = tuple(prefix)
    elif name.endswith(".md"):
        key_path = tuple(prefix) + (name[:-3],)
    else:
        return None
    return NarrativeNode(narrative_root=narrative_root, key_path=key_path)


def narrative_destination_path_to_node(git_root: Path, path: Path) -> NarrativeNode | None:
    """Map a narrative path to a node when the path may not exist yet (rename destination)."""
    try:
        root = git_root.resolve()
        rel = path.resolve().relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[0] != "narrative":
        return None
    slug = parts[1]
    narrative_root = root / "narrative" / slug
    rest = parts[2:]
    if not rest:
        return None
    last = rest[-1]
    if last.endswith(".md"):
        if last == "_node.md":
            key_path = tuple(rest[:-1])
        else:
            key_path = tuple(rest[:-1]) + (last[:-3],)
    else:
        key_path = tuple(rest)
    return NarrativeNode(narrative_root=narrative_root, key_path=key_path)


def prune_tts_orphans(project_root: Path, node: NarrativeNode) -> None:
    backend = get_mount_backend(project_root)
    if backend is None:
        return
    if not node_uses_tts_cache(node):
        return
    wanted = {c.id for c in chunks_for_node_text(node.md_path().read_text(encoding="utf-8"))}
    prefix = tts_cache_mount_prefix(node)
    entries = backend.list_dir(prefix)
    if entries is None:
        return
    for e in entries:
        if e.get("is_dir"):
            continue
        name = str(e.get("name", ""))
        if not name.endswith(".mp3"):
            continue
        stem = name[: -len(".mp3")]
        if stem not in wanted:
            backend.delete(f"{prefix}/{name}")


def remove_tts_cache_subtree(
    project_root: Path,
    node: NarrativeNode,
    *,
    raw_md: str | None = None,
) -> None:
    backend = get_mount_backend(project_root)
    if backend is None:
        return
    body = raw_md if raw_md is not None else node.md_path().read_text(encoding="utf-8")
    if not text_has_tts_cached(body):
        return
    backend.delete_tree(tts_cache_mount_prefix(node))


def move_tts_cache_subtree(
    project_root: Path,
    old: NarrativeNode,
    new: NarrativeNode,
    *,
    old_had_tts: bool,
) -> None:
    if not old_had_tts:
        return
    backend = get_mount_backend(project_root)
    if backend is None:
        return
    src = tts_cache_mount_prefix(old)
    dst = tts_cache_mount_prefix(new)
    if src == dst:
        return
    backend.move_tree(src, dst)


def migrate_collate_verbatim_audio(
    project_root: Path,
    *,
    parent_node: NarrativeNode,
    child_node: NarrativeNode,
    selected_text: str,
    parent_had_tts: bool,
) -> None:
    if not parent_had_tts:
        return
    backend = get_mount_backend(project_root)
    if backend is None:
        return
    pfx_p = tts_cache_mount_prefix(parent_node)
    pfx_c = tts_cache_mount_prefix(child_node)
    for ch in chunks_for_node_text(selected_text):
        name = f"{ch.id}.mp3"
        src = f"{pfx_p}/{name}"
        dst = f"{pfx_c}/{name}"
        if not backend.file_exists(src):
            continue
        if backend.file_exists(dst):
            continue
        backend.move(src, dst)


def maybe_prune_tts_after_narrative_write(git_root: Path, path: Path) -> None:
    node = narrative_storage_path_to_node(git_root, path)
    if node is None or not path.is_file():
        return
    if not path.name.endswith(".md"):
        return
    prune_tts_orphans(git_root, node)


def maybe_move_tts_cache_on_narrative_rename(git_root: Path, src: Path, dst: Path) -> None:
    old = narrative_storage_path_to_node(git_root, src)
    new = narrative_destination_path_to_node(git_root, dst)
    if old is None or new is None:
        return
    fm_src = src / "_node.md" if src.is_dir() else src
    try:
        src_body = fm_src.read_text(encoding="utf-8")
    except OSError:
        return
    old_had = text_has_tts_cached(src_body)
    move_tts_cache_subtree(git_root, old, new, old_had_tts=old_had)


def _alternate_node_backing_exists(path: Path) -> bool:
    """True if *path* is one of two filesystem layouts for the same ``key_path`` (leaf vs folder).

    :func:`NarrativeNode.to_folder` / :func:`NarrativeNode.to_leaf` delete the alternate file
    while the node (and its TTS prefix) remain — cache removal must not run on that delete.
    """
    try:
        resolved = path.resolve()
        if resolved.name == "_node.md":
            parent_dir = resolved.parent
            leaf = parent_dir.parent / f"{parent_dir.name}.md"
            return leaf.is_file()
        if resolved.suffix == ".md":
            folder_md = resolved.parent / resolved.stem / "_node.md"
            return folder_md.is_file()
    except OSError:
        return False
    return False


def maybe_remove_tts_cache_before_narrative_delete(git_root: Path, path: Path) -> None:
    node = narrative_storage_path_to_node(git_root, path)
    if node is None or not path.is_file():
        return
    if _alternate_node_backing_exists(path):
        return
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return
    remove_tts_cache_subtree(git_root, node, raw_md=body)
