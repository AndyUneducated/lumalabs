"""Per-tile visual similarity (SSIM + perceptual hash)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .constants import COMPARE_WIDTH


def _load_gray_array(path: Path, width: int = COMPARE_WIDTH) -> np.ndarray:
    img = Image.open(path).convert("L")
    if img.width != width:
        ratio = width / img.width
        new_h = max(1, int(img.height * ratio))
        img = img.resize((width, new_h), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float64)


def _align_arrays(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return a[:h, :w], b[:h, :w]


def _ssim_window(a: np.ndarray, b: np.ndarray, window: int = 11) -> float:
    a, b = _align_arrays(a, b)
    if a.size == 0:
        return 0.0
    h, w = a.shape
    if h < window or w < window:
        return float(1.0 - np.mean(np.abs(a - b)) / 255.0)

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    scores: list[float] = []
    for y in range(0, h - window + 1, window):
        for x in range(0, w - window + 1, window):
            patch_a = a[y : y + window, x : x + window]
            patch_b = b[y : y + window, x : x + window]
            mu_a = patch_a.mean()
            mu_b = patch_b.mean()
            sigma_a = patch_a.var()
            sigma_b = patch_b.var()
            sigma_ab = ((patch_a - mu_a) * (patch_b - mu_b)).mean()
            num = (2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)
            den = (mu_a**2 + mu_b**2 + c1) * (sigma_a + sigma_b + c2)
            scores.append(num / den if den else 1.0)
    return float(np.mean(scores)) if scores else 0.0


def _dhash(img: Image.Image, hash_size: int = 8) -> int:
    gray = img.convert("L").resize(
        (hash_size + 1, hash_size), Image.Resampling.BILINEAR
    )
    pixels = list(gray.getdata())
    bits = 0
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def score_visual(
    src_tiles: list[Path], out_tiles: list[Path]
) -> dict[str, Any]:
    if not src_tiles or not out_tiles:
        return {"ssim": 0.0, "phash": 0.0, "raw": 0.0, "tiles": []}

    tile_scores: list[dict[str, Any]] = []
    ssims: list[float] = []
    phash_sims: list[float] = []

    for i in range(min(len(src_tiles), len(out_tiles))):
        src_path, out_path = src_tiles[i], out_tiles[i]
        if not src_path.is_file() or not out_path.is_file():
            continue
        src_arr = _load_gray_array(src_path)
        out_arr = _load_gray_array(out_path)
        ssim = _ssim_window(src_arr, out_arr)
        ssims.append(ssim)

        src_img = Image.open(src_path)
        out_img = Image.open(out_path)
        src_hash = _dhash(src_img)
        out_hash = _dhash(out_img)
        ham = _hamming(src_hash, out_hash)
        phash_sim = 1.0 - ham / 64.0
        phash_sims.append(phash_sim)

        tile_scores.append(
            {
                "tile": i + 1,
                "ssim": round(ssim, 4),
                "phash_similarity": round(phash_sim, 4),
            }
        )

    mean_ssim = float(np.mean(ssims)) if ssims else 0.0
    mean_phash = float(np.mean(phash_sims)) if phash_sims else 0.0
    raw = 0.7 * mean_ssim + 0.3 * mean_phash
    return {
        "ssim": round(mean_ssim, 4),
        "phash": round(mean_phash, 4),
        "raw": round(raw, 4),
        "tiles": tile_scores,
    }
