"""Convergence state and A/B naked baseline."""

from __future__ import annotations

import convergence
import server_state
from agent_loop import run_naked_baseline
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["insights"])


@router.get("/convergence")
async def get_convergence(session_id: str | None = None):
    return convergence.get_state(session_id)


class ABRequest(BaseModel):
    url: str
    session_id: str
    profile: str = "balanced"


@router.post("/ab")
async def run_ab_baseline(req: ABRequest):
    res = await run_naked_baseline(req.url, req.profile)
    if res.get("error"):
        return res
    baseline = convergence.set_baseline(req.session_id, res["report"], url=req.url)
    server_state.notify("convergence")
    return {"baseline": baseline}
