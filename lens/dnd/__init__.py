"""D&D dataset extension: balance_encounter and check_stat command tools, plus CLI."""

from __future__ import annotations

from pathlib import Path

from lens.core.dataset_extensions import register_extension_command
from lens.dnd.balance_encounter import register_tools
from lens.dnd.check_stat import register_tools as register_check_stat_tools
from lens.dnd.cli import app


def register(
    *,
    dataset_name: str,
    dataset_path: Path,
    project_root: Path | None,
) -> None:
    register_extension_command("dnd", app)
    register_tools(
        dataset_path=dataset_path,
        dataset_name=dataset_name,
        project_root=project_root,
    )
    register_check_stat_tools(dataset_name=dataset_name)
