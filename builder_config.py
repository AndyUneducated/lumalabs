"""Shared paths and model settings for server + MCP tools."""

from __future__ import annotations

import os
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
SHOTS_DIR = OUTPUT_DIR / ".shots"
SESSIONS_DIR = Path.home() / ".claude" / "projects"
AGENT_MODEL = os.environ.get("AGENT_MODEL", "haiku")
