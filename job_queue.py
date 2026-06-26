"""Async job queue for heavy capture work (stateless API + worker pool).

Jobs are persisted under data/jobs/ so a single instance survives restarts.
Concurrency is capped via CAPTURE_WORKERS; per-client quotas via QUOTA_PER_HOUR.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine

from builder_config import CAPTURE_WORKERS, JOBS_DIR, QUOTA_PER_HOUR, QUOTA_WINDOW_SEC

_queue: asyncio.Queue[str] | None = None
_worker_tasks: list[asyncio.Task] = []
_semaphore: asyncio.Semaphore | None = None
_handlers: dict[str, Callable[[dict], Coroutine[Any, Any, dict]]] = {}
_quota: dict[str, list[float]] = {}


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    id: str
    type: str
    status: JobStatus
    client_key: str
    payload: dict
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict | None = None
    error: str | None = None
    position: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save_job(job: JobRecord) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _job_path(job.id).write_text(json.dumps(job.to_dict(), indent=2) + "\n")


def load_job(job_id: str) -> JobRecord | None:
    path = _job_path(job_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return JobRecord(
        id=data["id"],
        type=data["type"],
        status=JobStatus(data["status"]),
        client_key=data.get("client_key", "anonymous"),
        payload=data.get("payload", {}),
        created_at=data["created_at"],
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        result=data.get("result"),
        error=data.get("error"),
        position=data.get("position"),
    )


def list_jobs(limit: int = 20) -> list[JobRecord]:
    if not JOBS_DIR.is_dir():
        return []
    paths = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[JobRecord] = []
    for path in paths[:limit]:
        try:
            job = load_job(path.stem)
            if job:
                out.append(job)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def register_handler(job_type: str, fn: Callable[[dict], Coroutine[Any, Any, dict]]) -> None:
    _handlers[job_type] = fn


def _prune_quota(client_key: str) -> None:
    now = time.monotonic()
    window = _quota.get(client_key, [])
    window = [t for t in window if now - t < QUOTA_WINDOW_SEC]
    _quota[client_key] = window


def check_quota(client_key: str) -> tuple[bool, int, int]:
    """Return (allowed, used_in_window, limit)."""
    _prune_quota(client_key)
    used = len(_quota.get(client_key, []))
    return used < QUOTA_PER_HOUR, used, QUOTA_PER_HOUR


def consume_quota(client_key: str) -> None:
    _prune_quota(client_key)
    _quota.setdefault(client_key, []).append(time.monotonic())


def queue_depth() -> int:
    if _queue is None:
        return 0
    return _queue.qsize()


def active_workers() -> int:
    if _semaphore is None:
        return 0
    return CAPTURE_WORKERS - _semaphore._value  # noqa: SLF001


async def enqueue(
    job_type: str,
    payload: dict,
    *,
    client_key: str = "anonymous",
) -> JobRecord:
    allowed, used, limit = check_quota(client_key)
    if not allowed:
        raise QuotaExceededError(
            f"Quota exceeded: {used}/{limit} jobs in the last {QUOTA_WINDOW_SEC // 3600}h"
        )
    if job_type not in _handlers:
        raise ValueError(f"Unknown job type: {job_type}")

    consume_quota(client_key)
    job_id = uuid.uuid4().hex[:12]
    job = JobRecord(
        id=job_id,
        type=job_type,
        status=JobStatus.QUEUED,
        client_key=client_key,
        payload=payload,
        created_at=_now_iso(),
        position=queue_depth() + 1,
    )
    save_job(job)
    assert _queue is not None
    await _queue.put(job_id)
    return job


async def _run_job(job_id: str) -> None:
    assert _semaphore is not None
    job = load_job(job_id)
    if not job or job.status != JobStatus.QUEUED:
        return

    async with _semaphore:
        job.status = JobStatus.RUNNING
        job.started_at = _now_iso()
        job.position = None
        save_job(job)

        handler = _handlers.get(job.type)
        if not handler:
            job.status = JobStatus.FAILED
            job.error = f"No handler for {job.type}"
            job.finished_at = _now_iso()
            save_job(job)
            return

        try:
            result = await handler(job.payload)
            job.status = JobStatus.COMPLETED
            job.result = result
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)[:500]
        job.finished_at = _now_iso()
        save_job(job)


async def _worker_loop(worker_id: int) -> None:
    assert _queue is not None
    while True:
        job_id = await _queue.get()
        try:
            await _run_job(job_id)
        finally:
            _queue.task_done()


async def start_workers() -> None:
    global _queue, _semaphore, _worker_tasks
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _queue = asyncio.Queue()
    _semaphore = asyncio.Semaphore(CAPTURE_WORKERS)
    _worker_tasks = [
        asyncio.create_task(_worker_loop(i), name=f"capture-worker-{i}")
        for i in range(CAPTURE_WORKERS)
    ]


async def stop_workers() -> None:
    for task in _worker_tasks:
        task.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
    _worker_tasks.clear()


class QuotaExceededError(Exception):
    pass
