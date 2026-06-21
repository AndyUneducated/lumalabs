"""Agent chat, session metadata, and fidelity profile listing."""

from __future__ import annotations

import asyncio
import json
import sys
import traceback

import server_state
from agent_loop import format_agent_error, run_agent
from builder_config import OUTPUT_FILE
from compare import load_config
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["agent"])

_background_tasks: set = set()


class ChatRequest(BaseModel):
    message: str
    url: str | None = None
    session_id: str | None = None
    fidelity_profile: str = "balanced"


@router.get("/fidelity/profiles")
async def fidelity_profiles():
    cfg = load_config()
    profiles = cfg.get("profiles", {})
    return {
        "default": "balanced",
        "profiles": [
            {
                "id": pid,
                "label": pdata.get("label", pid),
                "description": pdata.get("description", ""),
            }
            for pid, pdata in profiles.items()
            if pid in ("more_editable", "balanced", "more_faithful")
        ],
    }


@router.get("/chat/status")
async def chat_status():
    return {"busy": server_state.agent_busy}


@router.get("/chat/session/{session_id}/resumable")
async def session_resumable(session_id: str):
    return {"resumable": server_state.can_resume_session(session_id)}


def _task_done(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return
    server_state.log("error", f"task exception: {exc!r}")
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    server_state.push_chat({"type": "error", "text": format_agent_error(exc)})


@router.post("/chat")
async def chat(req: ChatRequest):
    task = asyncio.create_task(
        run_agent(
            req.message,
            url=req.url,
            session_id=req.session_id,
            fidelity_profile=req.fidelity_profile,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_task_done)
    return {"status": "started"}


@router.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    meta = server_state.session_store.get(session_id) or {}
    sdir = server_state.get_session_dir()
    if not sdir:
        return {"messages": [], "url": meta.get("url"), "fidelity_profile": meta.get("fidelity_profile")}
    jsonl_path = sdir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return {"messages": [], "url": meta.get("url"), "fidelity_profile": meta.get("fidelity_profile")}

    messages = []
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") == "user":
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, str) and content:
                messages.append({"role": "user", "text": content})
        elif entry.get("type") == "assistant":
            blocks = entry.get("message", {}).get("content", [])
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        messages.append({"role": "assistant", "text": text})

    return {
        "messages": messages,
        "url": meta.get("url"),
        "fidelity_profile": meta.get("fidelity_profile"),
    }


@router.get("/chat/sessions")
async def list_sessions():
    return {"sessions": [{"id": k, **v} for k, v in server_state.session_store.items()]}


@router.post("/chat/reset-all")
async def reset_all_sessions():
    sdir = server_state.get_session_dir()
    if sdir:
        for f in sdir.glob("*.jsonl"):
            f.unlink()
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    server_state.session_store.clear()
    server_state.save_sessions()
    server_state.notify("html_updated")
    return {"reset": True}
