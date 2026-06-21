"""Fidelity JSON config loading and profile resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_PROFILE,
    FIDELITY_CONFIG_PATH,
    PROFILE_ALIASES,
    VALID_PROFILES,
)


def resolve_profile(profile: str | None) -> str:
    if profile in PROFILE_ALIASES:
        profile = PROFILE_ALIASES[profile]
    if profile in VALID_PROFILES:
        return profile
    return DEFAULT_PROFILE


def default_config() -> dict[str, Any]:
    return {
        "weights": {
            "content": 0.30,
            "structure": 0.20,
            "layout": 0.30,
            "visual": 0.20,
        },
        "thresholds": {"pass": 0.85, "warn": 0.70},
        "hard_gates": {
            "text_coverage": 0.95,
            "landmark_order_exact": False,
            "min_block_iou": 0.30,
        },
        "bands": {
            "content": {"floor": 0.15, "ceil": 1.0},
            "structure": {"floor": 0.10, "ceil": 1.0},
            "layout": {"floor": 0.05, "ceil": 0.85},
            "visual": {"floor": 0.20, "ceil": 0.98},
            "assets": {"floor": 0.0, "ceil": 1.0},
        },
        "profiles": {
            "more_editable": {
                "weights": {
                    "content": 0.35,
                    "structure": 0.0,
                    "layout": 0.25,
                    "visual": 0.40,
                    "assets": 0.0,
                },
                "hard_gates": {
                    "text_coverage": 0.90,
                    "landmark_order_exact": False,
                    "min_block_iou": 0.25,
                },
                "thresholds": {"pass": 0.80, "warn": 0.65},
            },
            "balanced": {
                "weights": {
                    "content": 0.30,
                    "structure": 0.05,
                    "layout": 0.35,
                    "visual": 0.30,
                    "assets": 0.0,
                },
                "hard_gates": {
                    "text_coverage": 0.95,
                    "landmark_order_exact": False,
                    "min_block_iou": 0.30,
                },
                "thresholds": {"pass": 0.85, "warn": 0.70},
            },
            "more_faithful": {
                "weights": {
                    "content": 0.20,
                    "structure": 0.0,
                    "layout": 0.28,
                    "visual": 0.32,
                    "assets": 0.20,
                },
                "hard_gates": {
                    "text_coverage": 0.95,
                    "landmark_order_exact": False,
                    "min_block_iou": 0.35,
                    "asset_coverage": 0.75,
                },
                "thresholds": {"pass": 0.82, "warn": 0.68},
            },
        },
    }


def load_config(path: Path | None = None, profile: str | None = None) -> dict[str, Any]:
    cfg_path = path or FIDELITY_CONFIG_PATH
    cfg = default_config()
    if cfg_path.is_file():
        loaded = json.loads(cfg_path.read_text())
        for key in ("weights", "thresholds", "hard_gates", "bands", "profiles"):
            if key in loaded:
                if key == "profiles":
                    cfg["profiles"] = {**cfg.get("profiles", {}), **loaded["profiles"]}
                else:
                    cfg[key] = {**cfg.get(key, {}), **loaded[key]}

    prof = resolve_profile(profile)
    prof_cfg = cfg.get("profiles", {}).get(prof, {})
    for key in ("weights", "thresholds", "hard_gates"):
        if key in prof_cfg:
            cfg[key] = {**cfg.get(key, {}), **prof_cfg[key]}
    cfg["profile"] = prof
    return cfg
