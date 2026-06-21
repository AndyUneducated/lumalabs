"""Output HTML version history (snapshots, rollback, diff)."""

from __future__ import annotations

import server_state
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["history"])


class RollbackRequest(BaseModel):
    seq: int


@router.get("/history")
async def get_history():
    from history import list_history

    return {"entries": list_history()}


@router.get("/history/diff")
async def get_history_diff(seq: int | None = None):
    from history import diff

    return {"diff": diff(seq)}


@router.post("/history/rollback")
async def rollback_history(req: RollbackRequest):
    from history import restore

    result = restore(req.seq)
    if result.get("error"):
        return result
    server_state.notify("html_updated")
    return result


@router.post("/history/revert-last")
async def revert_last_history():
    from history import revert_last

    result = revert_last()
    if result.get("error"):
        return result
    server_state.notify("html_updated")
    return result
