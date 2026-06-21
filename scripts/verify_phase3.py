#!/usr/bin/env python3
"""Quick verification for Phase 3 exit criteria (no agent)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tokens import (  # noqa: E402
    categorize,
    extract_tokens_from_styles,
    list_tokens_from_html,
    parse_root_vars,
    patch_root_vars,
    rgb_to_hex,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html><head><style>
:root {
  --color-brand: #2563eb;
  --color-text: #1c1917;
  --font-base: Inter, sans-serif;
}
body { color: var(--color-text); background: var(--color-brand); }
</style></head><body><h1>Hi</h1></body></html>
"""


def test_rgb_to_hex():
    assert rgb_to_hex("rgb(37, 99, 235)") == "#2563eb"
    assert rgb_to_hex("#FF00AA") == "#ff00aa"
    assert rgb_to_hex("rgba(0, 0, 0, 0.5)") == "rgba(0, 0, 0, 0.5)"
    print("OK rgb_to_hex")


def test_parse_root_vars():
    parsed = parse_root_vars(SAMPLE_HTML)
    assert parsed["--color-brand"] == "#2563eb"
    assert parsed["--font-base"] == "Inter, sans-serif"
    print("OK parse_root_vars")


def test_patch_root_vars_roundtrip():
    updated = patch_root_vars(SAMPLE_HTML, {"--color-brand": "#7c3aed"})
    assert "#7c3aed" in updated
    assert "<h1>Hi</h1>" in updated
    reparsed = parse_root_vars(updated)
    assert reparsed["--color-brand"] == "#7c3aed"
    assert reparsed["--color-text"] == "#1c1917"
    print("OK patch_root_vars roundtrip")


def test_patch_appends_missing():
    html = "<style>:root { --color-brand: red; }</style>"
    patched = patch_root_vars(html, {"--color-accent": "#00ff00"})
    assert "--color-accent: #00ff00" in patched
    print("OK patch_appends_missing")


def test_extract_from_styles():
    styles = {
        "palette": [{"color": "rgb(37, 99, 235)", "count": 10}],
        "typography": {
            "bodyFontFamily": "Georgia, serif",
            "bodyFontSize": "16px",
            "bodyColor": "rgb(28, 25, 23)",
            "bodyBackground": "rgb(250, 250, 249)",
            "h1FontFamily": "Georgia, serif",
            "h1FontSize": "32px",
            "h1FontWeight": "700",
        },
        "buttonSample": {
            "backgroundColor": "rgb(37, 99, 235)",
            "borderRadius": "6px",
            "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
            "padding": "12px 24px",
        },
    }
    tokens = extract_tokens_from_styles(styles)
    assert tokens["--color-brand"] == "#2563eb"
    assert tokens["--font-base"] == "Georgia, serif"
    assert tokens["--radius"] == "6px"
    print("OK extract_from_styles")


def test_list_tokens_from_html():
    rows = list_tokens_from_html(SAMPLE_HTML)
    names = [r["name"] for r in rows]
    assert "--color-brand" in names
    assert categorize("--color-brand") == "color"
    assert categorize("--font-base") == "typography"
    print("OK list_tokens_from_html")


def main():
    test_rgb_to_hex()
    test_parse_root_vars()
    test_patch_root_vars_roundtrip()
    test_patch_appends_missing()
    test_extract_from_styles()
    test_list_tokens_from_html()
    print("\nAll Phase 3 unit checks passed.")


if __name__ == "__main__":
    main()
