#!/usr/bin/env python3
"""Quick verification for Phase 2 exit criteria (no agent)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compare import fidelity_report, load_config, score_content, score_structure  # noqa: E402


def _base_payload():
    return {
        "text": ["Welcome to Acme", "Build faster", "Get started today"],
        "skeleton": ["header", "main", "section", "h1", "section", "footer"],
        "sections": [
            {"tag": "header", "id": "top", "box": {"x": 0, "y": 0, "w": 1, "h": 0.1}},
            {"tag": "main", "id": None, "box": {"x": 0, "y": 0.1, "w": 1, "h": 0.6}},
            {"tag": "footer", "id": "foot", "box": {"x": 0, "y": 0.85, "w": 1, "h": 0.15}},
        ],
        "viewport": {"width": 1280, "scrollHeight": 2000},
    }


def test_footer_regression():
    src = _base_payload()
    out = _base_payload()
    out["skeleton"] = ["header", "main", "section", "h1", "section"]
    out["sections"] = [s for s in out["sections"] if s["tag"] != "footer"]

    struct = score_structure(src, out)
    assert not struct["landmark_order_exact"], "footer removal should break landmark order"
    assert "footer" in struct["missing_landmarks"], "footer should be in missing landmarks"
    report = fidelity_report(src, out, [], [], load_config())
    worst = [w["section"] for w in report["worst_sections"]]
    assert any("footer" in s for s in worst), f"footer should be in worst_sections: {worst}"
    print("OK footer regression")


def test_heading_text_only():
    src = _base_payload()
    out = _base_payload()
    out["text"] = ["Totally different headline", "Build faster", "Get started today"]

    content = score_content(src, out)
    assert content["coverage"] < 1.0, "heading change should lower coverage"
    report = fidelity_report(src, out, [], [], load_config())
    assert report["axes"]["content"]["raw"] < report["axes"]["layout"]["raw"]
    assert report["axes"]["structure"]["raw"] >= report["axes"]["content"]["raw"]
    print("OK heading text-only drop")


def test_visual_deterministic():
    shots = ROOT / "output" / ".shots"
    pngs = sorted(shots.glob("*.png"))
    if len(pngs) < 1:
        print("SKIP visual deterministic (no PNG tiles in output/.shots)")
        return
    p = pngs[0]
    from compare import score_visual

    a = score_visual([p], [p])
    b = score_visual([p], [p])
    assert abs(a["ssim"] - b["ssim"]) < 1e-6
    assert abs(a["raw"] - b["raw"]) < 1e-6
    print(f"OK visual deterministic SSIM={a['ssim']}")


def test_report_shape():
    src = _base_payload()
    report = fidelity_report(src, src, [], [], load_config())
    for axis in ("content", "structure", "layout", "visual"):
        assert axis in report["axes"], f"missing axis {axis}"
    assert report["worst_sections"] is not None
    assert report["verdict"] in ("pass", "warn", "fail")
    print("OK report shape:", json.dumps({k: report[k] for k in ("verdict", "total")}))


def test_profile_more_editable_skips_structure_gate():
    src = _base_payload()
    out = _base_payload()
    out["skeleton"] = ["header", "main", "footer"]
    report = fidelity_report(src, out, [], [], load_config(profile="more_editable"))
    assert report["profile"] == "more_editable"
    assert not any("structure" in g for g in report.get("gate_failures", []))
    print("OK more_editable profile skips structure gate")


def test_asset_gate_only_more_faithful():
    manifest = {
        "assets": {
            "logo": {"local": "assets/logo.png", "preview_path": "/assets/logo.png"},
            "favicon": {"local": "assets/fav.ico", "preview_path": "/assets/fav.ico"},
        }
    }
    html_with = '<img src="/assets/logo.png"><link rel="icon" href="/assets/fav.ico">'
    html_without = "<p>no assets</p>"
    from compare import score_assets

    good = fidelity_report(
        _base_payload(), _base_payload(), [], [],
        load_config(profile="more_faithful"),
        asset_manifest=manifest, output_html=html_with,
    )
    assert good["axes"]["assets"]["enforced"] is True
    assert not any("assets:" in g for g in good["gate_failures"])

    bad = fidelity_report(
        _base_payload(), _base_payload(), [], [],
        load_config(profile="more_faithful"),
        asset_manifest=manifest, output_html=html_without,
    )
    assert any("assets:" in g for g in bad["gate_failures"])

    balanced = fidelity_report(
        _base_payload(), _base_payload(), [], [],
        load_config(profile="balanced"),
        asset_manifest=manifest, output_html=html_without,
    )
    assert balanced["axes"]["assets"]["enforced"] is False
    assert not any("assets:" in g for g in balanced["gate_failures"])
    print("OK asset_coverage gate only in more_faithful")


def test_font_and_inline_svg_reference():
    from compare import score_assets
    from assets import asset_referenced_in_html

    font_entry = {
        "family": "Inter",
        "local": "assets/fonts/site-inter-abc.woff2",
        "preview_path": "/assets/fonts/site-inter-abc.woff2",
    }
    svg_entry = {
        "local": "assets/site-logo-inline-deadbeef.svg",
        "preview_path": "/assets/site-logo-inline-deadbeef.svg",
    }
    html = (
        '<style>@font-face { font-family: "Inter"; '
        'src: url("/assets/fonts/site-inter-abc.woff2"); }</style>'
        '<img src="/assets/site-logo-inline-deadbeef.svg" alt="logo">'
    )
    assert asset_referenced_in_html(font_entry, html)
    assert asset_referenced_in_html(svg_entry, html)
    manifest = {"assets": {"font": font_entry, "logo": svg_entry}}
    scored = score_assets(manifest, html)
    assert scored["coverage"] == 1.0
    assert set(scored["matched"]) == {"font", "logo"}
    print("OK font and inline_svg asset reference")


def main():
    test_report_shape()
    test_footer_regression()
    test_heading_text_only()
    test_profile_more_editable_skips_structure_gate()
    test_asset_gate_only_more_faithful()
    test_font_and_inline_svg_reference()
    test_visual_deterministic()
    print("\nAll Phase 2 unit checks passed.")


if __name__ == "__main__":
    main()
