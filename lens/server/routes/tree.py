from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, is_dataset_root
from lens.server.dependencies import get_session

router = APIRouter()


def _node_to_dict(node: NarrativeNode) -> dict[str, Any]:
    children = [_node_to_dict(node.child_node(key)) for key in node.child_keys()]
    return {
        "address": str(node.to_address()),
        "key": node.key_path[-1] if node.key_path else node.narrative_root.name,
        "is_folder": node.is_folder_node(),
        "children": children,
    }


@router.get("/tree")
def tree(session: ProjectSession = Depends(get_session)) -> list[dict[str, Any]]:
    if is_dataset_root(session.project_root):
        return []
    narrative_dir = session.project_root / "narrative"
    if not narrative_dir.exists():
        return []
    result: list[dict[str, Any]] = []
    for d in sorted(narrative_dir.iterdir()):
        if d.is_dir():
            root_node = NarrativeNode(narrative_root=d, key_path=())
            if root_node.exists():
                result.append(_node_to_dict(root_node))
    return result
