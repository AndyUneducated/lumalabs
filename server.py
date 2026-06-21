"""FastAPI server for the website builder.

Serves the viewer, hosts the HTML preview, and runs the agent.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.pop("CLAUDECODE", None)

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# SSE subscribers
_subscribers: list[asyncio.Queue] = []
_version = 0

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
SESSIONS_DIR = Path.home() / ".claude" / "projects"
AGENT_MODEL = os.environ.get("AGENT_MODEL", "opus")


def _detect_claude_transport() -> str:
    """Report which Claude Code CLI the SDK is likely to use (no secrets)."""
    if cli := shutil.which("claude"):
        return f"claude CLI at {cli}"
    try:
        import claude_agent_sdk

        bundled = (
            Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        )
        if bundled.is_file():
            return f"bundled CLI at {bundled}"
    except ImportError:
        pass
    return "claude CLI not found in PATH (SDK may fail until installed)"


def _startup_selfcheck() -> None:
    """Print runtime config to stderr; never log secrets."""
    env_file = Path(".env")
    print("[startup] AGENT_MODEL:", AGENT_MODEL, file=sys.stderr)
    print("[startup] transport:", _detect_claude_transport(), file=sys.stderr)
    print(
        "[startup] .env file:",
        "present" if env_file.is_file() else "not found",
        file=sys.stderr,
    )


def _get_session_dir() -> Path | None:
    """Find the Claude session storage directory for this project."""
    cwd = Path.cwd().resolve()
    slug = str(cwd).replace("/", "-")
    d = SESSIONS_DIR / slug
    return d if d.exists() else None


def _notify(event: str = "update") -> None:
    global _version
    _version += 1
    data = json.dumps({"version": _version, "event": event})
    for q in list(_subscribers):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)
    from tools import set_notify_fn
    set_notify_fn(_notify)
    _load_sessions()
    _startup_selfcheck()
    yield
    from browser import close_browser
    await close_browser()


app = FastAPI(title="Website Builder", lifespan=lifespan)


# --- Viewer ---


@app.get("/", response_class=HTMLResponse)
async def viewer():
    return FileResponse("viewer.html", headers={"Cache-Control": "no-store"})


# --- SSE ---


@app.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.append(q)

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
            _subscribers.remove(q)

    return EventSourceResponse(stream())


# --- HTML preview ---


@app.get("/preview", response_class=HTMLResponse)
async def preview():
    if OUTPUT_FILE.exists():
        return FileResponse(OUTPUT_FILE, headers={"Cache-Control": "no-store"})
    return HTMLResponse(
        "<html><body></body></html>"
    )


# --- Chat (agent) ---

SYSTEM_PROMPT = """\
You are an AI agent that creates customizable website templates from existing sites.

The user gives you a URL of a site they love. Your job is to recreate it as \
clean, editable HTML/CSS that looks and feels almost exactly like the original — \
same layout, same colors, same typography, same visual rhythm — but with clean \
code that's easy to customize.

You have tools to capture screenshots, write and read HTML, and screenshot your \
own output. The user sees a live preview of your HTML.

When the user gives you a URL, follow this workflow strictly:

1. **Look first** — call `capture_site(url)` before writing any HTML. Study the \
screenshot tiles (top to bottom) and the extracted styles JSON. Match what you \
see in the pixels, not what you guess from memory.

2. **Build** — call `write_html` with clean semantic HTML and a <style> block. \
Use the real colors, fonts, spacing, and layout from the capture. No frameworks, \
no inline styles on every element.

3. **Self-check** — call `screenshot_output()` and compare your output to the \
target screenshots. Fix the biggest visual gaps (layout, colors, typography, \
spacing, hero, CTA).

4. **Iterate** — repeat steps 2–3 at most 2–3 times, then stop and summarize \
what you matched and what still differs.

For follow-up edits (no new URL), use `read_html`, make focused changes, and \
optionally `screenshot_output()` to verify.

If `capture_site` returns a DOM-only fallback (no images), use the style JSON \
and text outline; do not invent a generic template.
"""


_agent_lock = asyncio.Lock()


def _build_agent_options(resume_session: str | None = None):
    import sys
    from claude_agent_sdk import ClaudeAgentOptions
    from tools import create_tool_server, TOOL_NAMES, SERVER_NAME

    os.environ.pop("CLAUDECODE", None)

    cs = create_tool_server()
    mcp_tool_names = [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES]

    print(f"[agent] Tools: {mcp_tool_names}, resume={resume_session}", file=sys.stderr)

    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        permission_mode="acceptEdits",
        model=AGENT_MODEL,
        mcp_servers={SERVER_NAME: cs},
        allowed_tools=mcp_tool_names + ["WebFetch", "WebSearch"],
        disallowed_tools=[
            "Bash", "Write", "Edit", "Read", "Glob", "Grep",
            "Agent", "Skill", "ToolSearch",
            "NotebookEdit", "TodoWrite",
        ],
        max_turns=30,
        cwd=str(Path.cwd()),
        continue_conversation=False,
        resume=resume_session,
    )


def _push_chat(data: dict):
    import sys
    encoded = json.dumps({"version": _version, "event": "chat", "chat": data})
    print(f"[chat] {data.get('type')}: {str(data.get('text', ''))[:80]}", file=sys.stderr)
    for q in list(_subscribers):
        try:
            q.put_nowait(encoded)
        except asyncio.QueueFull:
            pass


_agent_busy = False


# Simple session metadata store: {session_id: {url, created}}
_sessions: dict[str, dict] = {}
SESSIONS_META_FILE = Path("data/sessions.json")


def _load_sessions():
    global _sessions
    if SESSIONS_META_FILE.exists():
        _sessions = json.loads(SESSIONS_META_FILE.read_text())


def _save_sessions():
    SESSIONS_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_META_FILE.write_text(json.dumps(_sessions, indent=2))


class ChatRequest(BaseModel):
    message: str
    url: str | None = None
    session_id: str | None = None


@app.get("/chat/status")
async def chat_status():
    return {"busy": _agent_busy}


_background_tasks: set = set()


@app.post("/chat")
async def chat(req: ChatRequest):
    task = asyncio.create_task(_run_agent(req.message, url=req.url, session_id=req.session_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_task_done)
    return {"status": "started"}


def _task_done(task):
    import sys
    if task.exception():
        print(f"[agent] TASK EXCEPTION: {task.exception()}", file=sys.stderr)
        import traceback
        traceback.print_exception(type(task.exception()), task.exception(), task.exception().__traceback__, file=sys.stderr)
        _push_chat({"type": "error", "text": str(task.exception())})


async def _run_agent(message: str, url: str | None = None, session_id: str | None = None):
    global _agent_busy
    async with _agent_lock:
        _agent_busy = True
        try:
            import sys
            from claude_agent_sdk import ClaudeSDKClient

            os.environ.pop("CLAUDECODE", None)
            opts = _build_agent_options(resume_session=session_id)

            print(f"[agent] Starting (resume={session_id}): {message[:80]}", file=sys.stderr)

            seen_texts = set()
            session_pushed = False

            # Snapshot existing sessions to detect the new one
            sdir = _get_session_dir()
            existing_files = set(sdir.glob("*.jsonl")) if sdir else set()

            async with ClaudeSDKClient(options=opts) as client:
                await client.query(message)

                # Detect new session file immediately after query starts
                if sdir:
                    for _ in range(10):
                        current = set(sdir.glob("*.jsonl"))
                        new_files = current - existing_files
                        if new_files:
                            new_sid = new_files.pop().stem
                            session_pushed = True
                            _push_chat({"type": "session", "session_id": new_sid})
                            if new_sid not in _sessions:
                                from datetime import datetime
                                _sessions[new_sid] = {"url": url or "", "created": datetime.now().isoformat()}
                                _save_sessions()
                            print(f"[agent] Session: {new_sid}", file=sys.stderr)
                            break
                        await asyncio.sleep(0.1)

                async for msg in client.receive_response():
                    msg_type = type(msg).__name__
                    print(f"[agent] msg: {msg_type}", file=sys.stderr)

                    if hasattr(msg, "content"):
                        for block in getattr(msg, "content", []):
                            if hasattr(block, "text") and block.text:
                                text = block.text.strip()
                                if text and text not in seen_texts:
                                    seen_texts.add(text)
                                    _push_chat({"type": "text", "text": text})

                    if hasattr(msg, "result") and msg.result:
                        text = msg.result.strip()
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            _push_chat({"type": "result", "text": text})

                    # Fallback: get session ID from ResultMessage
                    if not session_pushed and hasattr(msg, "session_id") and msg.session_id:
                        session_pushed = True
                        sid = msg.session_id
                        _push_chat({"type": "session", "session_id": sid})
                        if sid not in _sessions:
                            from datetime import datetime
                            _sessions[sid] = {"url": url or "", "created": datetime.now().isoformat()}
                            _save_sessions()

            _push_chat({"type": "done"})
            print("[agent] Done", file=sys.stderr)

        except Exception as e:
            import sys
            print(f"[agent] Error: {e}", file=sys.stderr)
            _push_chat({"type": "error", "text": str(e)})
        finally:
            _agent_busy = False


@app.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    """Load chat history from the Claude session JSONL file."""
    sdir = _get_session_dir()
    if not sdir:
        return {"messages": []}
    jsonl_path = sdir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return {"messages": []}

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

    return {"messages": messages}


@app.get("/chat/sessions")
async def list_sessions():
    return {"sessions": [{"id": k, **v} for k, v in _sessions.items()]}


@app.post("/chat/reset-all")
async def reset_all_sessions():
    sdir = _get_session_dir()
    if sdir:
        for f in sdir.glob("*.jsonl"):
            f.unlink()
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    _sessions.clear()
    _save_sessions()
    _notify("html_updated")
    return {"reset": True}


@app.post("/chat/reset")
async def reset_chat():
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    _notify("html_updated")
    return {"reset": True}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print(f"\nWebsite builder running on http://localhost:{args.port}\n")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=args.port,
        reload=True,
        reload_includes=["*.py", "viewer.html"],
        reload_excludes=["output/*", "data/*"],
        timeout_graceful_shutdown=1,
    )
