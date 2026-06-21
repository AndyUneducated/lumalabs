"""Content, structure, layout, and asset axis scores."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from .constants import LANDMARK_TAGS, TEXT_MATCH_THRESHOLD


def _norm_text(s: str) -> str:
    """Normalize text for matching: unicode-fold, collapse all whitespace.

    Handles NBSP / full-width spaces, case, and surrounding punctuation so
    visually-identical blocks (e.g. "© 2026 Acme" vs "©2026 Acme") match.
    """
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKC", s)
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
