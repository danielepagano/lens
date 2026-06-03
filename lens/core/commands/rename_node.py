"""Rename a narrative node: update the parent annotation and rename the backing file/dir."""

from __future__ import annotations

from lens.core.annotations import parse_annotations
from lens.core.narrative import NarrativeNode
from lens.core.project import validate_slug
from lens.core.storage import Storage


def rename_node(node: NarrativeNode, new_slug: str, storage: Storage) -> str:
    """Rename *node* to *new_slug* and return the effective new slug.

    If the node's current slug is prefixed with its operator name (e.g.
    ``play-who-are-you`` was created by the ``play`` operator), the same
    prefix is prepended automatically when the user omits it — so
    ``rename … the-necromancer`` produces ``play-the-necromancer``.

    Updates the open (and close, if present) annotation in the parent file,
    then renames the backing ``.md`` file or folder on disk.

    Raises:
        ValueError: if *node* is the root, *new_slug* is invalid, or the
            resulting slug already exists as a sibling.
    """
    if not node.key_path:
        raise ValueError("cannot rename the root narrative node")
    if not validate_slug(new_slug):
        raise ValueError(
            f"invalid slug '{new_slug}' (alphanumeric, underscores, hyphens only)"
        )

    old_slug = node.key_path[-1]

    parent = NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path[:-1],
    )
    parent_path = parent.md_path()
    text = parent_path.read_text(encoding="utf-8")
    annotations = parse_annotations(text)

    # Detect whether the old slug carries an operator prefix (e.g. "design-",
    # "play-").  If so, auto-prepend the same prefix to the new slug so the
    # user can provide just the label part (e.g. "paris" → "design-paris").
    open_ann = next(
        (a for a in annotations if a.id == old_slug and not a.closing and not a.self_closing),
        None,
    )
    if open_ann is not None:
        prefix = f"{open_ann.operator}-"
        if old_slug.startswith(prefix) and not new_slug.startswith(prefix):
            new_slug = prefix + new_slug

    if old_slug == new_slug:
        return new_slug  # no-op

    sibling_keys = set(parent.child_keys())
    if new_slug in sibling_keys:
        raise ValueError(f"a node named '{new_slug}' already exists here")

    # ----------------------------------------------------------------
    # Rewrite parent file: update open + close annotation IDs
    # ----------------------------------------------------------------
    lines = text.split("\n")

    for ann in annotations:
        if ann.id != old_slug:
            continue
        # line_start is 1-based; lines[line_start - 1] is the first line
        # of the annotation (contains the operator:id).
        idx = ann.line_start - 1
        # Replace :old_slug with :new_slug only in the operator:id position.
        # The annotation line looks like "[operator:old-slug]: #" (single-line)
        # or "[operator:old-slug" (multi-line start).
        old_tag_fragment = f":{old_slug}"
        new_tag_fragment = f":{new_slug}"
        line = lines[idx]
        # Replace first occurrence to avoid touching unrelated content.
        lines[idx] = line.replace(old_tag_fragment, new_tag_fragment, 1)

    storage.write_file(parent_path, "\n".join(lines))

    # ----------------------------------------------------------------
    # Rename backing file or folder
    # ----------------------------------------------------------------
    if node.is_folder_node():
        # Folder node: narrative/<name>/.../<old_slug>/ → <new_slug>/
        old_dir = node.md_path().parent
        new_dir = old_dir.parent / new_slug
        storage.rename(old_dir, new_dir)
    else:
        # Leaf node: narrative/<name>/.../<old_slug>.md → <new_slug>.md
        old_file = node.md_path()
        new_file = old_file.parent / f"{new_slug}.md"
        storage.rename(old_file, new_file)

    return new_slug
