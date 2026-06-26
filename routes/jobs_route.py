"""Stateless job API: submit capture work, poll status, inspect queue stats."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import job_queue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CaptureJobRequest(BaseModel):
    url: str = Field(..., min_length=4, description="Public HTTP(S) URL to capture")


def _client_key(x_api_key: str | None, x_forwarded_for: str | None) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()[:64]
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()[:64]
    return "anonymous"


@router.post("/capture")
async def submit_capture(
    req: CaptureJobRequest,
    x_api_key: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
):
    """Enqueue a screenshot capture job. Returns immediately with a job id."""
    client = _client_key(x_api_key, x_forwarded_for)
    try:
        job = await job_queue.enqueue("capture", {"url": req.url}, client_key=client)
    except job_queue.QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    return {
        "job_id": job.id,
        "status": job.status.value,
        "position": job.position,
        "poll": f"/api/jobs/{job.id}",
    }


@router.get("/stats/queue")
async def queue_stats():
    allowed, used, limit = job_queue.check_quota("anonymous")
    return {
        "queue_depth": job_queue.queue_depth(),
        "active_workers": job_queue.active_workers(),
        "max_workers": int(__import__("builder_config").CAPTURE_WORKERS),
        "quota": {"used": used, "limit": limit, "remaining": max(0, limit - used)},
    }


@router.get("")
async def list_jobs(limit: int = 20):
    jobs = job_queue.list_jobs(limit=min(limit, 100))
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/{job_id}")
async def get_job(job_id: str):
    job = job_queue.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()
