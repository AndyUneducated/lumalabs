#!/usr/bin/env python3
"""Phase 7 verification: job queue, quotas, stateless capture API."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import job_queue  # noqa: E402
from builder_config import CAPTURE_WORKERS, QUOTA_PER_HOUR  # noqa: E402


async def _with_temp_jobs(fn):
    tmp = Path(tempfile.mkdtemp())
    orig = job_queue.JOBS_DIR
    orig_quota = job_queue._quota.copy()
    try:
        job_queue.JOBS_DIR = tmp
        job_queue._quota.clear()
        await fn()
    finally:
        job_queue.JOBS_DIR = orig
        job_queue._quota = orig_quota
        shutil.rmtree(tmp, ignore_errors=True)


async def test_enqueue_and_complete():
    async def run():
        async def handler(payload):
            await asyncio.sleep(0.01)
            return {"ok": True, "url": payload["url"]}

        job_queue.register_handler("capture", handler)
        await job_queue.start_workers()

        job = await job_queue.enqueue("capture", {"url": "https://example.com"}, client_key="test")
        assert job.status == job_queue.JobStatus.QUEUED

        for _ in range(50):
            loaded = job_queue.load_job(job.id)
            assert loaded is not None
            if loaded.status in (job_queue.JobStatus.COMPLETED, job_queue.JobStatus.FAILED):
                break
            await asyncio.sleep(0.05)

        assert loaded.status == job_queue.JobStatus.COMPLETED
        assert loaded.result == {"ok": True, "url": "https://example.com"}
        await job_queue.stop_workers()

    await _with_temp_jobs(run)
    print("ok test_enqueue_and_complete")


async def test_quota_blocks_over_limit():
    async def run():
        job_queue.register_handler("capture", lambda p: asyncio.sleep(0, result={}))
        orig_limit = job_queue.QUOTA_PER_HOUR
        job_queue.QUOTA_PER_HOUR = 2
        try:
            await job_queue.enqueue("capture", {"url": "https://a.com"}, client_key="q")
            await job_queue.enqueue("capture", {"url": "https://b.com"}, client_key="q")
            try:
                await job_queue.enqueue("capture", {"url": "https://c.com"}, client_key="q")
                raise AssertionError("expected QuotaExceededError")
            except job_queue.QuotaExceededError:
                pass
        finally:
            job_queue.QUOTA_PER_HOUR = orig_limit

    await _with_temp_jobs(run)
    print("ok test_quota_blocks_over_limit")


async def test_concurrency_cap():
    async def run():
        running = 0
        peak = 0
        lock = asyncio.Lock()

        async def slow_handler(_payload):
            nonlocal running, peak
            async with lock:
                running += 1
                peak = max(peak, running)
            await asyncio.sleep(0.08)
            async with lock:
                running -= 1
            return {"done": True}

        job_queue.register_handler("capture", slow_handler)
        await job_queue.start_workers()

        jobs = [
            await job_queue.enqueue("capture", {"url": f"https://x{i}.com"}, client_key=f"c{i}")
            for i in range(4)
        ]
        for _ in range(80):
            if all(
                (j := job_queue.load_job(jid.id)) and j.status == job_queue.JobStatus.COMPLETED
                for jid in jobs
            ):
                break
            await asyncio.sleep(0.05)

        await job_queue.stop_workers()
        assert peak <= CAPTURE_WORKERS, f"peak concurrency {peak} > {CAPTURE_WORKERS}"

    await _with_temp_jobs(run)
    print("ok test_concurrency_cap")


def test_api_routes():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert "capture_workers" in body

    stats = client.get("/api/jobs/stats/queue")
    assert stats.status_code == 200
    assert "queue_depth" in stats.json()

    missing = client.get("/api/jobs/doesnotexist")
    assert missing.status_code == 404

    print("ok test_api_routes")


def main():
    asyncio.run(test_enqueue_and_complete())
    asyncio.run(test_quota_blocks_over_limit())
    asyncio.run(test_concurrency_cap())
    test_api_routes()
    print("\nAll Phase 7 checks passed.")


if __name__ == "__main__":
    main()
