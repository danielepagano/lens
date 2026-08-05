from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.stats import get_stats
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


@router.get("/stats")
def stats(project_slug: str, session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    result = get_stats(session)
    transaction: dict[str, Any] | None = None
    if result.has_pending:
        storage = session.new_storage(owner=None)
        transaction = {
            "has_pending": True,
            "owner": str(result.pending_owner) if result.pending_owner is not None else None,
            "is_mutation": result.pending_owner is not None and result.pending_owner.operator == "edit",
            "raw_diff": storage.pending_diff(),
        }

    return {
        "active_narrative": session.active_narrative.narrative_root.name
        if session.active_narrative is not None
        else None,
        "narratives": [t[0] for t in result.trees],
        "cursor": str(result.cursor_addr) if result.cursor_addr is not None else None,
        "has_pending": result.has_pending,
        "has_staged": result.has_staged,
        "pending_owner": str(result.pending_owner) if result.pending_owner is not None else None,
        "dataset_name": result.dataset_name,
        "current_datasets": result.current_datasets if result.dataset_name is None else [],
        "kb_types": result.kb_types,
        "kb_count": result.kb_count,
        "effective_pins_at_cursor": result.effective_pins_at_cursor,
        "effective_vars_at_cursor": result.effective_vars_at_cursor,
        "effective_params_at_cursor": result.effective_params_at_cursor,
        "remember_pins_at_cursor": result.remember_pins_at_cursor,
        "available_llms": result.available_llms,
        "image_backends": result.image_backends,
        "has_mount": result.has_mount,
        "cloud_mount": result.cloud_mount,
        "reference_images_supported": result.reference_images_supported,
        "tts_available": result.tts_available,
        "active_session_operator": result.active_session_operator,
        "registered_modality_ids": result.registered_modality_ids,
        "modalities_at_cursor": result.modalities_at_cursor,
        "modality_warnings_at_cursor": result.modality_warnings_at_cursor,
        "effective_modalities_at_cursor": result.effective_modalities_at_cursor,
        "dataset_configs": result.dataset_configs,
        "release": {
            "enabled": result.release_enabled,
            "lens_repo_url": result.release_lens_repo_url,
            "requested_version": result.release_requested_version,
            "requested_from_commit": result.release_requested_from_commit,
            "app_leader": result.release_app_leader,
            "dataset_repos": result.release_dataset_repos,
            "installed_version": result.release_installed_version,
        } if result.dataset_name is None else None,
        "transaction": transaction,
    }
