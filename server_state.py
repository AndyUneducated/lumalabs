"""HTTP/SSE broadcast and chat session metadata (shared by server routes and agent_loop)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from builder_config import SESSIONS_DIR

_sse_subscribers: list[asyncio.Queue] = []
_version = 0


def register_sse_subscriber(q: asyncio.Queue) -> None:
    _sse_subscribers.append(q)


def unregister_sse_subscriber(q: asyncio.Queue) -> None:
    try:
        _sse_subscribers.remove(q)
    except ValueError:
        pass

agent_lock = asyncio.Lock()
agent_busy = False

session_store: dict[str, dict] = {}
SESSIONS_META_FILE = Path("data/sessions.json")


def notify(event: str = "update") -> None:
    global _version
    _version += 1
    data = json.dumps({"version": _version, "event": event})
    for q in list(_sse_subscribers):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


def log(tag: str, line: str, skipped: int = 0) -> None:
    skip = f" \033[2m(skip {skipped})\033[0m" if skipped else ""
    print(f"[{tag}]{skip} {line}".rstrip(), file=sys.stderr)


def push_chat(data: dict) -> None:
    encoded = json.dumps({"version": _version, "event": "chat", "chat": data})
    dtype = data.get("type")
    if dtype == "session":
        log("chat", f"session {data.get('session_id', '')}")
    elif dtype == "error":
        log("chat", f"error: {str(data.get('text', ''))[:80]}")
    for q in list(_sse_subscribers):
        try:
            q.put_nowait(encoded)
        except asyncio.QueueFull:
            pass


def get_session_dir() -> Path | None:
    cwd = Path.cwd().resolve()
    slug = str(cwd).replace("/", "-")
    d = SESSIONS_DIR / slug
    return d if d.exists() else None


def session_jsonl_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    sdir = get_session_dir()
    if not sdir:
        return None
    return sdir / f"{session_id}.jsonl"


def can_resume_session(session_id: str | None) -> bool:
    if not session_id:
        return False
    path = session_jsonl_path(session_id)
    return path is not None and path.is_file()


def load_sessions() -> None:
    global session_store
    if SESSIONS_META_FILE.exists():
        session_store = json.loads(SESSIONS_META_FILE.read_text())


def save_sessions() -> None:
    SESSIONS_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_META_FILE.write_text(json.dumps(session_store, indent=2))
