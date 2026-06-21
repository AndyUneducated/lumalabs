"""Server-Sent Events stream for preview + chat."""

from __future__ import annotations

import asyncio

import server_state
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["sse"])


@router.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    server_state.register_sse_subscriber(q)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"data": data}
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
        finally:
            server_state.unregister_sse_subscriber(q)

    return EventSourceResponse(stream())
