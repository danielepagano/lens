"""Server routes for the release system — reserved for Phase 2.

Phase 1 removed the legacy routes (status, policy, gated-update/approve,
gated-update/reject).  Phase 2 adds ``POST /{slug}/release/request`` and
folds release fields into ``GET /{slug}/stats``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/{project_slug}")
