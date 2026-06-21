"""MCP tools: fidelity compare and self-check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import convergence
from assets import load_manifest
from browser import capture_compare, friendly_capture_error
from builder_config import OUTPUT_FILE, SHOTS_DIR
from compare import diff_heatmap, fidelity_report, load_config, resolve_profile

from .state import (
    _normalize_url,
    _notify,
    get_asset_manifest_cache,
    get_fidelity_profile,
    get_target_cache,
)


def _manifest_for_url(url: str) -> dict | None:
    normalized = _normalize_url(url)
    cache = get_asset_manifest_cache()
    if normalized in cache:
        return cache[normalized]
    manifest = load_manifest()
    if manifest and manifest.get("source", "").rstrip("/") == normalized.rstrip("/"):
        cache[normalized] = manifest
        return manifest
    return None


def _shot_urls(paths: list[Path]) -> list[str]:
    return [f"/shots/{p.name}" for p in paths if p.is_file()]


async def run_fidelity_comparison(url: str, profile: str | None = None) -> dict[str, Any]:
    """Run Phase 2 fidelity compare; shared by compare_to_target and POST /compare."""
    prof = resolve_profile(profile or get_fidelity_profile())
    normalized = _normalize_url(url)
    tc = get_target_cache()

    target = tc.get(normalized)
    if target is None or target.compare_payload is None:
        target = await capture_compare(normalized, is_file=False)
        tc[normalized] = target

    if not OUTPUT_FILE.is_file():
        return {"error": "No output/index.html yet. Call write_html first."}

    output = await capture_compare(str(OUTPUT_FILE.resolve()), is_file=True)

    if target.compare_payload is None or output.compare_payload is None:
        parts = []
        if target.error:
            parts.append(f"Target: {friendly_capture_error(target.error)}")
        if output.error:
            parts.append(f"Output: {friendly_capture_error(output.error)}")
        detail = " ".join(parts) if parts else "Capture data unavailable."
        return {"error": "Could not compare pages.", "detail": detail}

    cfg = load_config(profile=prof)
    output_html = OUTPUT_FILE.read_text()
    manifest = _manifest_for_url(normalized)
    report = fidelity_report(
        target.compare_payload,
        output.compare_payload,
        target.paths,
        output.paths,
        cfg,
        asset_manifest=manifest,
        output_html=output_html,
    )
    diff_path = diff_heatmap(target.paths, output.paths)

    return {
        "report": report,
        "profile": prof,
        "source_tiles": _shot_urls(target.paths),
        "output_tiles": _shot_urls(output.paths),
        "heatmap": f"/shots/{diff_path.name}" if diff_path and diff_path.is_file() else None,
    }


async def compare_to_target(url: str, profile: str | None = None):
    """Compare output/index.html to the target URL with a fidelity report.

    Returns per-axis scores (content, structure, layout, visual), a weighted
    total, verdict (pass/warn/fail), gate failures, and worst sections to fix.
    Call after write_html during the self-check loop.

    Args:
        url: Target site URL (same URL used in capture_site)
        profile: Fidelity knob — more_editable, balanced (default), or more_faithful
    """
    prof = resolve_profile(profile or get_fidelity_profile())
    result = await run_fidelity_comparison(url, profile=prof)

    if result.get("error"):
        msg = result["error"]
        if result.get("detail"):
            msg += " " + result["detail"]
        return {"content": [{"type": "text", "text": msg}]}

    report = result["report"]
    prof = result.get("profile", prof)

    if convergence.record_round(report) is not None:
        _notify("convergence")

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Fidelity report (profile={prof}, JSON):\n"
                + json.dumps(report, indent=2)
            ),
        }
    ]
    esc = convergence.faithfulness_escalation_note(prof)
    if esc:
        content.append({"type": "text", "text": esc})
    heatmap = result.get("heatmap")
    if heatmap:
        heatmap_path = SHOTS_DIR / Path(heatmap).name
        if heatmap_path.is_file():
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"Diff heatmap saved to: {heatmap_path} "
                        "(open in the viewer Insights tab; not embedded to stay under SDK size limits)."
                    ),
                }
            )

    return {"content": content}
