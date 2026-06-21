"""Diff heatmap image generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from builder_config import SHOTS_DIR

from .visual import _align_arrays, _load_gray_array


def _colorize_diff(diff: np.ndarray) -> np.ndarray:
    """Map a 0..255 grayscale diff to a blue→green→yellow→red RGB heatmap."""
    norm = np.clip(diff / 255.0, 0.0, 1.0)
    stops = np.array(
        [
            [0.0, 0.10, 0.30, 0.60],
            [13, 71, 255, 255],
            [27, 200, 235, 40],
            [120, 120, 30, 30],
        ]
    )
    pos = stops[0]
    r = np.interp(norm, pos, stops[1])
    g = np.interp(norm, pos, stops[2])
    b = np.interp(norm, pos, stops[3])
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def diff_heatmap(
    src_tiles: list[Path], out_tiles: list[Path]
) -> Path | None:
    """Save a color diff heatmap (blue=match, red=large difference)."""
    if not src_tiles or not out_tiles:
        return None

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    strips: list[Image.Image] = []

    for i in range(min(len(src_tiles), len(out_tiles))):
        if not src_tiles[i].is_file() or not out_tiles[i].is_file():
            continue
        src_arr = _load_gray_array(src_tiles[i])
        out_arr = _load_gray_array(out_tiles[i])
        a, b = _align_arrays(src_arr, out_arr)
        diff = np.abs(a - b)

        heat = _colorize_diff(diff)

        base_h, base_w = diff.shape
        base = (b[:base_h, :base_w] * 0.35).astype(np.uint8)
        base_rgb = np.stack([base, base, base], axis=-1)

        alpha = np.clip(diff / 255.0, 0.0, 1.0)[..., None] * 0.85
        blended = (base_rgb * (1 - alpha) + heat * alpha).astype(np.uint8)
        strips.append(Image.fromarray(blended, mode="RGB"))

    if not strips:
        return None

    total_h = sum(s.height for s in strips)
    max_w = max(s.width for s in strips)
    canvas = Image.new("RGB", (max_w, total_h), (10, 12, 30))
    y = 0
    for strip in strips:
        canvas.paste(strip, (0, y))
        y += strip.height

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = SHOTS_DIR / f"diff-heatmap-{ts}.png"
    canvas.save(out_path)
    return out_path
