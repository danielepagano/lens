from __future__ import annotations

import io
from pathlib import Path
import tomli_w

from lens.core.project import find_git_root
from lens.core.storage import Storage
from lens.core.exceptions import LensException

def init_project() -> Path:
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
    return root
