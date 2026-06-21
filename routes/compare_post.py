"""Manual fidelity compare (same pipeline as the MCP tool)."""

from __future__ import annotations

from browser import friendly_capture_error
from fastapi import APIRouter
from pydantic import BaseModel
from tools import run_fidelity_comparison

router = APIRouter(tags=["compare"])


class CompareRequest(BaseModel):
    url: str
    profile: str = "balanced"


@router.post("/compare")
async def run_compare(req: CompareRequest):
    result = await run_fidelity_comparison(req.url, profile=req.profile)
    if result.get("error"):
        err = result["error"]
        detail = result.get("detail")
        if detail:
            detail = friendly_capture_error(detail) if len(str(detail)) > 80 else detail
        return {
            "error": friendly_capture_error(err) if err == "Could not compare pages." else err,
            "detail": detail,
        }
    return result
