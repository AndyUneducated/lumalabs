"""Axis score normalization helpers."""

from __future__ import annotations


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize_axis(raw: float, floor: float, ceil: float) -> float:
    span = ceil - floor
    if span <= 1e-9:
        return 1.0 if raw >= ceil else 0.0
    return clamp((raw - floor) / span)
