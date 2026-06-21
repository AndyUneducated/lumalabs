"""Weighted fidelity report and hard gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .axes import score_assets, score_content, score_layout, score_structure
from .config import DEFAULT_PROFILE, load_config
from .norm import normalize_axis
from .visual import score_visual


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
            normalize_axis(raw, band["floor"], band["ceil"]),
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
