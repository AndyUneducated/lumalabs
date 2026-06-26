"""Health and readiness probes for deployment."""

from __future__ import annotations

import os

from fastapi import APIRouter

import job_queue
from builder_config import AGENT_MODEL, CAPTURE_WORKERS, QUOTA_PER_HOUR

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_model": AGENT_MODEL,
        "capture_workers": CAPTURE_WORKERS,
        "quota_per_hour": QUOTA_PER_HOUR,
        "queue_depth": job_queue.queue_depth(),
        "active_workers": job_queue.active_workers(),
        "version": os.environ.get("APP_VERSION", "dev"),
    }
