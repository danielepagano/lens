from __future__ import annotations

import io
from pathlib import Path
import tomli_w

from lens.core.commands.skill import install_skill
from lens.core.project import find_git_root
from lens.core.storage import Storage
from lens.core.exceptions import LensException

def init_project(*, skill: bool = True) -> Path:
    """Create the project scaffold, and by default the agent skill pointer.

    The pointer is installed by default because the failure it prevents is an
    agent that never learns the project has a CLI at all — and nobody
    remembers to opt in to that.  It is a pointer, not guidance, so it does not
    age (see :mod:`lens.core.commands.skill`).
    """
    try:
        root = find_git_root()
    except RuntimeError as e:
        raise LensException(str(e)) from e

    storage = Storage(root)
    lens_toml = root / "lens.toml"
    if not lens_toml.exists():
        storage.write_file(lens_toml, "[project]\n# narrative selection set by 'lens use <slug>'\n")

    storage.mkdir(root / "knowledge")
    tags_toml = root / "knowledge" / "tags.toml"
    if not tags_toml.exists():
        buf = io.BytesIO()
        tomli_w.dump({}, buf)
        storage.write_file_bytes(tags_toml, buf.getvalue())

    storage.mkdir(root / "narrative")

    if skill:
        install_skill(root, storage=storage)
    return root
