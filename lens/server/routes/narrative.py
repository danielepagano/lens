from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from lens.core.address import NarrativeAddress
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, is_dataset_root
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


def _node_to_dict(node: NarrativeNode) -> dict[str, Any]:
    children = [_node_to_dict(node.child_node(key)) for key in node.child_keys()]
    return {
        "address": str(node.to_address()),
        "key": node.key_path[-1] if node.key_path else node.narrative_root.name,
        "children": children,
    }


@router.get("/narrative/tree")
def tree(project_slug: str, session: ProjectSession = Depends(get_session)) -> list[dict[str, Any]]:
    if is_dataset_root(session.project_root):
        return []
    if session.active_narrative is None:
        return []
    root = session.active_narrative
    return [_node_to_dict(root)]


@router.get("/narrative/node/{address:path}")
def node(
    project_slug: str, address: str, session: ProjectSession = Depends(get_session)
) -> dict[str, Any]:
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative nodes in dataset mode")

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if addr.narrative is None:
        if session.active_narrative is None:
            raise HTTPException(status_code=400, detail="no active narrative")
        addr = addr.with_narrative(session.active_narrative.narrative_root.name)

    try:
        node_obj = addr.to_node(session.project_root)
        content = node_obj.md_path().read_text()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {address}")

    return {
        "address": str(addr.node_only()),
        "content": content,
        "children": node_obj.child_keys(),
    }
