"""``GET /{slug}/explain`` — prompt composition report for a cursor.

Read-only: the core call opens no transaction and makes no model call, so
this route is safe to hit at any time, including mid-session.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from lens.core.commands.explain import (
    DEFAULT_CHARS_PER_TOKEN,
    SORT_CHOICES,
    SORT_ORDER,
    explain_context,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, is_dataset_root
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


@router.get("/explain")
def explain(
    project_slug: str,
    address: str | None = None,
    line: int | None = Query(None, ge=1),
    operator: str | None = None,
    prompt: str | None = None,
    sort: str = Query(SORT_ORDER, pattern=f"^({'|'.join(SORT_CHOICES)})$"),
    chars_per_token: int = Query(DEFAULT_CHARS_PER_TOKEN, ge=1, le=32),
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    _ = project_slug
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative context in dataset mode")
    try:
        report = explain_context(
            session,
            address=address,
            line=line,
            operator=operator,
            prompt=prompt,
            sort=sort,
            chars_per_token=chars_per_token,
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return report.to_dict()
