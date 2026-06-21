"""Pure fidelity scoring (Phase 2). Public API preserved for `from compare import …`."""

from __future__ import annotations

from builder_config import SHOTS_DIR

from .axes import score_assets, score_content, score_layout, score_structure
from .config import default_config, load_config, resolve_profile
from .constants import (
    COMPARE_WIDTH,
    DEFAULT_PROFILE,
    FIDELITY_CONFIG_PATH,
    LANDMARK_TAGS,
    PROFILE_ALIASES,
    TEXT_MATCH_THRESHOLD,
    VALID_PROFILES,
)
from .heatmap import diff_heatmap
from .report import fidelity_report
from .visual import score_visual

__all__ = [
    "COMPARE_WIDTH",
    "DEFAULT_PROFILE",
    "FIDELITY_CONFIG_PATH",
    "LANDMARK_TAGS",
    "PROFILE_ALIASES",
    "SHOTS_DIR",
    "TEXT_MATCH_THRESHOLD",
    "VALID_PROFILES",
    "default_config",
    "diff_heatmap",
    "fidelity_report",
    "load_config",
    "resolve_profile",
    "score_assets",
    "score_content",
    "score_layout",
    "score_structure",
    "score_visual",
]
