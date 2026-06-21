"""Pure fidelity scoring for Phase 2 (no Playwright imports).

Compares source vs output payloads and PNG tiles on four axes:
content, structure, layout, visual.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

FIDELITY_CONFIG_PATH = Path("data/fidelity.json")
SHOTS_DIR = Path("output") / ".shots"
COMPARE_WIDTH = 1280

LANDMARK_TAGS = frozenset({"header", "nav", "main", "section", "footer"})
TEXT_MATCH_THRESHOLD = 0.8
VALID_PROFILES = ("more_editable", "balanced", "more_faithful")
DEFAULT_PROFILE = "balanced"
PROFILE_ALIASES = {
    "editable": "more_editable",
    "faithful": "more_faithful",
}


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


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _normalize_axis(raw: float, floor: float, ceil: float) -> float:
    span = ceil - floor
    if span <= 1e-9:
        return 1.0 if raw >= ceil else 0.0
    return _clamp((raw - floor) / span)


def _best_text_match(block: str, candidates: list[str]) -> float:
    if not candidates:
        return 0.0
    return max(difflib.SequenceMatcher(None, block, c).ratio() for c in candidates)


def _norm_text(s: str) -> str:
    """Normalize text for matching: unicode-fold, collapse all whitespace.

    Handles NBSP / full-width spaces, case, and surrounding punctuation so
    visually-identical blocks (e.g. "© 2026 Acme" vs "©2026 Acme") match.
    """
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKC", s)
    # Drop all whitespace (incl. NBSP, full-width) so spacing never breaks a match.
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.casefold()


def score_content(src: dict, out: dict) -> dict[str, Any]:
    src_blocks = list(src.get("text") or [])
    out_blocks = list(out.get("text") or [])
    if not src_blocks:
        return {
            "coverage": 1.0,
            "order": 1.0,
            "raw": 1.0,
            "missing_blocks": [],
        }

    out_norm = [_norm_text(b) for b in out_blocks]

    matched_indices: list[int] = []
    missing: list[str] = []
    for block in src_blocks:
        block_norm = _norm_text(block)
        best_ratio = 0.0
        best_idx = -1
        for i, out_block in enumerate(out_norm):
            if not block_norm or not out_block:
                continue
            # Containment counts as a full match (handles split/merged blocks).
            if block_norm in out_block or out_block in block_norm:
                best_ratio = 1.0
                best_idx = i
                break
            ratio = difflib.SequenceMatcher(None, block_norm, out_block).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        if best_ratio >= TEXT_MATCH_THRESHOLD:
            matched_indices.append(best_idx)
        else:
            missing.append(block[:120])

    coverage = (len(src_blocks) - len(missing)) / len(src_blocks)
    order = 1.0
    if len(matched_indices) >= 2:
        order = difflib.SequenceMatcher(None, matched_indices, sorted(matched_indices)).ratio()

    raw = 0.7 * coverage + 0.3 * order
    return {
        "coverage": round(coverage, 4),
        "order": round(order, 4),
        "raw": round(raw, 4),
        "missing_blocks": missing[:12],
    }


def _landmark_subsequence(skeleton: list[str]) -> list[str]:
    out: list[str] = []
    for tag in skeleton:
        if tag in LANDMARK_TAGS:
            out.append(tag)
    return out


def score_structure(src: dict, out: dict) -> dict[str, Any]:
    src_sk = list(src.get("skeleton") or [])
    out_sk = list(out.get("skeleton") or [])
    similarity = (
        difflib.SequenceMatcher(None, src_sk, out_sk).ratio()
        if src_sk or out_sk
        else 1.0
    )

    src_lm = _landmark_subsequence(src_sk)
    out_lm = _landmark_subsequence(out_sk)
    landmark_order_exact = src_lm == out_lm
    missing_landmarks = [t for t in src_lm if t not in out_lm]

    return {
        "similarity": round(similarity, 4),
        "landmark_order_exact": landmark_order_exact,
        "missing_landmarks": missing_landmarks[:12],
        "raw": round(similarity, 4),
    }


def _box_dims(box: dict) -> tuple[float, float, float, float]:
    """Safe x,y,w,h for compare payloads (missing keys → 0)."""
    try:
        x = float(box.get("x", 0))
        y = float(box.get("y", 0))
        w = float(box.get("w", 0))
        h = float(box.get("h", 0))
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0, 0.0
    return x, y, max(w, 0.0), max(h, 0.0)


def _box_iou(a: dict, b: dict) -> float:
    ax1, ay1, aw, ah = _box_dims(a)
    bx1, by1, bw, bh = _box_dims(b)
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(aw * ah, 1e-9)
    area_b = max(bw * bh, 1e-9)
    return inter / (area_a + area_b - inter)


def score_layout(src: dict, out: dict) -> dict[str, Any]:
    src_secs = list(src.get("sections") or [])
    out_secs = list(out.get("sections") or [])
    if not src_secs:
        return {"mean_iou": 1.0, "raw": 1.0, "sections": []}

    out_by_tag: dict[str, list[dict]] = {}
    for sec in out_secs:
        out_by_tag.setdefault(sec.get("tag", "?"), []).append(sec)

    src_by_tag_count: dict[str, int] = {}
    section_scores: list[dict[str, Any]] = []
    ious: list[float] = []

    for src_sec in src_secs:
        tag = src_sec.get("tag", "?")
        occ = src_by_tag_count.get(tag, 0)
        src_by_tag_count[tag] = occ + 1
        candidates = out_by_tag.get(tag, [])
        src_box = src_sec.get("box") or {}

        if occ < len(candidates):
            out_sec = candidates[occ]
            out_box = out_sec.get("box") or {}
            best_iou = _box_iou(src_box, out_box)
            best_dy = abs((src_box.get("y", 0)) - (out_box.get("y", 0)))
        else:
            best_iou = 0.0
            best_dy = 0.0

        ious.append(best_iou)
        label = tag
        if src_sec.get("id"):
            label = f"{tag}#{src_sec['id']}"
        section_scores.append(
            {
                "section": label,
                "iou": round(best_iou, 4),
                "dy": round(best_dy, 4),
            }
        )

    mean_iou = sum(ious) / len(ious) if ious else 0.0
    return {
        "mean_iou": round(mean_iou, 4),
        "raw": round(mean_iou, 4),
        "sections": section_scores,
    }


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
    pad = window // 2
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


def score_assets(manifest: dict | None, output_html: str) -> dict[str, Any]:
    """Fraction of mirrored role assets (logo, favicon, hero, font) referenced in output HTML."""
    if not manifest:
        return {
            "coverage": None,
            "raw": None,
            "matched": [],
            "missing": [],
            "skipped": True,
            "informational": True,
        }

    role_assets: dict = manifest.get("assets") or {}
    if not role_assets:
        return {
            "coverage": None,
            "raw": None,
            "matched": [],
            "missing": [],
            "skipped": True,
            "informational": True,
        }

    from assets import asset_referenced_in_html

    matched: list[str] = []
    missing: list[str] = []
    for role, entry in role_assets.items():
        if asset_referenced_in_html(entry, output_html):
            matched.append(role)
        else:
            missing.append(role)

    coverage = len(matched) / len(role_assets) if role_assets else 1.0
    return {
        "coverage": round(coverage, 4),
        "raw": round(coverage, 4),
        "matched": matched,
        "missing": missing,
        "manifest_roles": list(role_assets.keys()),
        "informational": False,
    }


def _build_worst_sections(
    content: dict,
    structure: dict,
    layout: dict,
    visual: dict,
    assets: dict | None = None,
    include_assets: bool = False,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for block in content.get("missing_blocks") or []:
        issues.append(
            {
                "section": f"text:{block[:40]}",
                "axis": "content",
                "severity": 1.0 - content.get("coverage", 0),
                "detail": f"Missing text block: {block[:80]}",
            }
        )

    for tag in structure.get("missing_landmarks") or []:
        issues.append(
            {
                "section": tag,
                "axis": "structure",
                "severity": 0.9,
                "detail": f"Missing landmark: {tag}",
            }
        )

    for sec in layout.get("sections") or []:
        iou = sec.get("iou", 1.0)
        if iou < 0.5:
            issues.append(
                {
                    "section": sec.get("section", "?"),
                    "axis": "layout",
                    "severity": 1.0 - iou,
                    "detail": f"IoU {iou:.2f}, vertical offset {sec.get('dy', 0):.2f}",
                }
            )

    for tile in visual.get("tiles") or []:
        ssim = tile.get("ssim", 1.0)
        if ssim < 0.65:
            issues.append(
                {
                    "section": f"tile-{tile.get('tile', '?')}",
                    "axis": "visual",
                    "severity": 1.0 - ssim,
                    "detail": f"Tile SSIM {ssim:.2f}",
                }
            )

    if include_assets and assets:
        for role in assets.get("missing") or []:
            issues.append(
                {
                    "section": f"asset:{role}",
                    "axis": "assets",
                    "severity": 0.95,
                    "detail": f"Mirrored {role} not referenced in output HTML",
                }
            )

    issues.sort(key=lambda x: x["severity"], reverse=True)
    return issues[:10]


def _check_hard_gates(
    content: dict,
    structure: dict,
    layout: dict,
    gates: dict[str, Any],
    assets: dict | None = None,
    profile: str = DEFAULT_PROFILE,
) -> list[str]:
    failures: list[str] = []
    min_cov = gates.get("text_coverage", 0.95)
    if content.get("coverage", 0) < min_cov:
        failures.append(
            f"content: text coverage {content.get('coverage')} < {min_cov}"
        )

    if gates.get("landmark_order_exact", True) and not structure.get(
        "landmark_order_exact", False
    ):
        failures.append("structure: landmark order does not match source")

    min_iou = gates.get("min_block_iou", 0.30)
    for sec in layout.get("sections") or []:
        if sec.get("iou", 1.0) < min_iou:
            failures.append(
                f"layout: {sec.get('section')} IoU {sec.get('iou')} < {min_iou}"
            )
            break

    # asset_coverage gate only applies in more_faithful mode
    min_assets = gates.get("asset_coverage")
    if profile == "more_faithful" and min_assets is not None and assets:
        if assets.get("skipped"):
            failures.append(
                "assets: run extract_assets(url) before compare in more_faithful mode"
            )
        elif (assets.get("coverage") or 0) < min_assets:
            missing = ", ".join(assets.get("missing") or []) or "unknown"
            failures.append(
                f"assets: coverage {assets.get('coverage')} < {min_assets} "
                f"(missing: {missing})"
            )

    return failures


def fidelity_report(
    src: dict,
    out: dict,
    src_tiles: list[Path],
    out_tiles: list[Path],
    cfg: dict[str, Any] | None = None,
    asset_manifest: dict | None = None,
    output_html: str = "",
) -> dict[str, Any]:
    """Full fidelity report with two-layer threshold logic."""
    config = cfg or load_config()
    weights = config["weights"]
    bands = config["bands"]
    thresholds = config["thresholds"]
    gates = config["hard_gates"]

    content = score_content(src, out)
    structure = score_structure(src, out)
    layout = score_layout(src, out)
    visual = score_visual(src_tiles, out_tiles)
    assets = score_assets(asset_manifest, output_html)
    prof = config.get("profile", DEFAULT_PROFILE)
    assets_weight = weights.get("assets", 0.0)
    assets_enforced = prof == "more_faithful" and assets_weight > 0

    axis_raw = {
        "content": content["raw"],
        "structure": structure["raw"],
        "layout": layout["raw"],
        "visual": visual["raw"],
    }
    if assets_enforced and not assets.get("skipped") and assets.get("raw") is not None:
        axis_raw["assets"] = assets["raw"]

    normalized = {}
    for axis, raw in axis_raw.items():
        band = bands.get(axis, {"floor": 0.0, "ceil": 1.0})
        normalized[axis] = round(
            _normalize_axis(raw, band["floor"], band["ceil"]),
            4,
        )

    total = round(
        sum(weights.get(axis, 0.0) * normalized.get(axis, 0.0) for axis in normalized),
        4,
    )

    gate_failures = _check_hard_gates(
        content, structure, layout, gates, assets=assets, profile=prof
    )
    worst_sections = _build_worst_sections(
        content,
        structure,
        layout,
        visual,
        assets=assets,
        include_assets=assets_enforced,
    )
    if weights.get("structure", 0) <= 0:
        worst_sections = [w for w in worst_sections if w.get("axis") != "structure"]

    pass_thr = thresholds.get("pass", 0.85)
    warn_thr = thresholds.get("warn", 0.70)

    if gate_failures:
        verdict = "fail"
    elif total >= pass_thr:
        verdict = "pass"
    elif total >= warn_thr:
        verdict = "warn"
    else:
        verdict = "fail"

    return {
        "profile": config.get("profile", DEFAULT_PROFILE),
        "verdict": verdict,
        "total": total,
        "axes": {
            "content": {**content, "normalized": normalized.get("content", 0)},
            "structure": {**structure, "normalized": normalized.get("structure", 0)},
            "layout": {**layout, "normalized": normalized.get("layout", 0)},
            "visual": {**visual, "normalized": normalized.get("visual", 0)},
            "assets": {
                **assets,
                "normalized": normalized.get("assets"),
                "enforced": assets_enforced,
            },
        },
        "weights": weights,
        "thresholds": thresholds,
        "gate_failures": gate_failures,
        "worst_sections": worst_sections,
    }


def _colorize_diff(diff: np.ndarray) -> np.ndarray:
    """Map a 0..255 grayscale diff to a blue→green→yellow→red RGB heatmap."""
    norm = np.clip(diff / 255.0, 0.0, 1.0)
    # Piecewise gradient: 0=blue (cold/identical) → 1=red (hot/different).
    stops = np.array(
        [
            [0.0, 0.10, 0.30, 0.60],   # position
            [13, 71, 255, 255],        # R
            [27, 200, 235, 40],        # G
            [120, 120, 30, 30],        # B
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
    """Save a color diff heatmap (blue=match, red=large difference).

    The per-pixel absolute grayscale difference is colorized and blended over
    a dimmed copy of the output screenshot so differences are easy to locate.
    """
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

        # Dimmed grayscale output as the base so the heat colors read clearly.
        base_h, base_w = diff.shape
        base = (b[:base_h, :base_w] * 0.35).astype(np.uint8)
        base_rgb = np.stack([base, base, base], axis=-1)

        # Blend more heat where the difference is larger.
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
