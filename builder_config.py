"""Shared paths and model settings for server + MCP tools."""

from __future__ import annotations

import os
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
SHOTS_DIR = OUTPUT_DIR / ".shots"
JOBS_DIR = Path("data/jobs")
SESSIONS_DIR = Path.home() / ".claude" / "projects"
AGENT_MODEL = os.environ.get("AGENT_MODEL", "haiku")
CAPTURE_WORKERS = max(1, int(os.environ.get("CAPTURE_WORKERS", "2")))
QUOTA_PER_HOUR = max(1, int(os.environ.get("QUOTA_PER_HOUR", "30")))
QUOTA_WINDOW_SEC = 3600
PORT = int(os.environ.get("PORT", "8000"))


def use_cli_oauth_auth() -> None:
    """Force Claude Agent SDK to use local Claude Code CLI OAuth, not API keys."""
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("CLAUDECODE", None)
