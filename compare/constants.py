"""Fidelity scoring constants (no heavy imports)."""

from __future__ import annotations

from pathlib import Path

FIDELITY_CONFIG_PATH = Path("data/fidelity.json")
COMPARE_WIDTH = 1280

LANDMARK_TAGS = frozenset({"header", "nav", "main", "section", "footer"})
TEXT_MATCH_THRESHOLD = 0.8
VALID_PROFILES = ("more_editable", "balanced", "more_faithful")
DEFAULT_PROFILE = "balanced"
PROFILE_ALIASES = {
    "editable": "more_editable",
    "faithful": "more_faithful",
}
