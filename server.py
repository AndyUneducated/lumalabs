"""FastAPI server for the website builder.

Serves the viewer, hosts the HTML preview, and runs the agent.
Route modules live under `routes/`; shared SSE + session state in `server_state.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

os.environ.pop("CLAUDECODE", None)

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from builder_config import AGENT_MODEL, OUTPUT_DIR
from fastapi import FastAPI
from routes.agent_route import router as agent_router
from routes.compare_post import router as compare_router
from routes.history_route import router as history_router
from routes.insights import router as insights_router
from routes.site import router as site_router
from routes.sse import router as sse_router
from routes.tokens_route import router as tokens_router

import server_state


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
    env_file = Path(".env")
    print("[startup] AGENT_MODEL:", AGENT_MODEL, file=sys.stderr)
    print("[startup] transport:", _detect_claude_transport(), file=sys.stderr)
    print(
        "[startup] .env file:",
        "present" if env_file.is_file() else "not found",
        file=sys.stderr,
    )


def _seed_fidelity_config() -> None:
    path = Path("data/fidelity.json")
    if path.is_file():
        return
    from compare import default_config

    path.write_text(json.dumps(default_config(), indent=2) + "\n")


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)
    _seed_fidelity_config()
    from tools import set_notify_fn

    set_notify_fn(server_state.notify)
    server_state.load_sessions()
    _startup_selfcheck()
    yield
    from browser import close_browser

    await close_browser()


app = FastAPI(title="Website Builder", lifespan=lifespan)

app.include_router(site_router)
app.include_router(sse_router)
app.include_router(compare_router)
app.include_router(insights_router)
app.include_router(history_router)
app.include_router(tokens_router)
app.include_router(agent_router)


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
