"""Design token extraction, parsing, and patching (Phase 3).

The :root block in output/index.html is the single source of truth.
"""

from __future__ import annotations

import re
from typing import Any

# Canonical vocabulary — prompt, panel, and tools use these exact names.
CANONICAL_TOKENS: dict[str, list[str]] = {
    "color": [
        "--color-brand",
        "--color-accent",
        "--color-bg",
        "--color-surface",
        "--color-text",
        "--color-muted",
        "--color-border",
    ],
    "typography": [
        "--font-base",
        "--font-heading",
        "--text-base",
        "--text-scale",
        "--leading",
        "--weight-heading",
    ],
    "shape": ["--radius", "--radius-lg", "--shadow"],
    "spacing": ["--space-unit", "--space-section"],
}

ALL_TOKEN_NAMES: list[str] = [
    name for names in CANONICAL_TOKENS.values() for name in names
]

DEFAULTS: dict[str, str] = {
    "--color-brand": "#2563eb",
    "--color-accent": "#2563eb",
    "--color-bg": "#fafaf9",
    "--color-surface": "#ffffff",
    "--color-text": "#1c1917",
    "--color-muted": "#78716c",
    "--color-border": "#e7e5e4",
    "--font-base": "Inter, system-ui, sans-serif",
    "--font-heading": "Inter, system-ui, sans-serif",
    "--text-base": "16px",
    "--text-scale": "1.25",
    "--leading": "1.5",
    "--weight-heading": "600",
    "--radius": "8px",
    "--radius-lg": "12px",
    "--shadow": "0 1px 3px rgba(0,0,0,0.1)",
    "--space-unit": "8px",
    "--space-section": "64px",
}

_ROOT_BLOCK_RE = re.compile(r":root\s*\{([^}]*)\}", re.DOTALL | re.IGNORECASE)
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def categorize(name: str) -> str:
    for cat, names in CANONICAL_TOKENS.items():
        if name in names:
            return cat
    return "other"


def rgb_to_hex(color: str | None) -> str | None:
    """Normalize rgb()/rgba() to hex; keep rgba() when alpha < 1."""
    if not color:
        return None
    c = color.strip()
    if c.startswith("#"):
        return c.lower()
    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)",
        c,
        re.IGNORECASE,
    )
    if not m:
        return c
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    alpha = m.group(4)
    if alpha is not None and float(alpha) < 1.0:
        return f"rgba({r}, {g}, {b}, {alpha})"
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_neutral(hex_color: str) -> bool:
    c = hex_color.lower()
    if not c.startswith("#") or len(c) < 7:
        return True
    try:
        r = int(c[1:3], 16)
        g = int(c[3:5], 16)
        b = int(c[5:7], 16)
    except ValueError:
        return True
    if max(r, g, b) - min(r, g, b) < 18 and (r + g + b) / 3 > 40:
        return True
    if r > 240 and g > 240 and b > 240:
        return True
    if r < 25 and g < 25 and b < 25:
        return True
    return False


def _pick_brand_color(palette: list[dict]) -> str | None:
    for entry in palette:
        raw = entry.get("color")
        hexed = rgb_to_hex(raw)
        if hexed and not _is_neutral(hexed):
            return hexed
    return None


def extract_tokens_from_styles(styles: dict[str, Any] | None) -> dict[str, str]:
    """Map browser capture styles JSON to canonical design tokens."""
    tokens = dict(DEFAULTS)
    if not styles:
        return tokens

    typo = styles.get("typography") or {}
    btn = styles.get("buttonSample") or {}
    card = styles.get("cardSample") or {}
    palette = styles.get("palette") or []

    brand = _pick_brand_color(palette)
    if brand:
        tokens["--color-brand"] = brand

    body_bg = rgb_to_hex(typo.get("bodyBackground"))
    if body_bg:
        tokens["--color-bg"] = body_bg

    body_text = rgb_to_hex(typo.get("bodyColor"))
    if body_text:
        tokens["--color-text"] = body_text

    accent = rgb_to_hex(btn.get("backgroundColor"))
    if accent and accent != body_bg:
        tokens["--color-accent"] = accent
    elif brand:
        tokens["--color-accent"] = brand

    h1_color = rgb_to_hex(typo.get("h1Color"))
    if h1_color and h1_color != body_text:
        tokens["--color-muted"] = h1_color

    sections = styles.get("sections") or []
    if sections:
        surf = rgb_to_hex(sections[0].get("backgroundColor"))
        if surf and surf != body_bg:
            tokens["--color-surface"] = surf

    body_font = typo.get("bodyFontFamily")
    if body_font:
        tokens["--font-base"] = body_font

    h1_font = typo.get("h1FontFamily")
    if h1_font:
        tokens["--font-heading"] = h1_font

    if typo.get("bodyFontSize"):
        tokens["--text-base"] = typo["bodyFontSize"]

    if typo.get("h1FontSize") and typo.get("bodyFontSize"):
        try:
            h1_px = float(re.sub(r"[^\d.]", "", typo["h1FontSize"]))
            body_px = float(re.sub(r"[^\d.]", "", typo["bodyFontSize"]))
            if body_px > 0:
                tokens["--text-scale"] = str(round(h1_px / body_px, 2))
        except ValueError:
            pass

    if typo.get("bodyLineHeight"):
        tokens["--leading"] = typo["bodyLineHeight"]

    if typo.get("h1FontWeight"):
        tokens["--weight-heading"] = typo["h1FontWeight"]

    radius = btn.get("borderRadius") or card.get("borderRadius")
    if radius and radius != "0px":
        tokens["--radius"] = radius
        tokens["--radius-lg"] = radius

    shadow = btn.get("boxShadow") or card.get("boxShadow")
    if shadow and shadow not in ("none", "0px 0px 0px 0px"):
        tokens["--shadow"] = shadow

    padding = btn.get("padding") or card.get("padding")
    if padding:
        parts = padding.split()
        if parts:
            tokens["--space-unit"] = parts[0]

    if sections and len(sections) >= 2:
        tokens["--space-section"] = "64px"

    return tokens


def parse_root_vars(html: str) -> dict[str, str]:
    """Parse CSS custom properties from the first :root block."""
    m = _ROOT_BLOCK_RE.search(html)
    if not m:
        return {}
    return {name: val.strip() for name, val in _VAR_RE.findall(m.group(1))}


def patch_root_vars(html: str, updates: dict[str, str]) -> str:
    """Patch variables inside the first :root block; append missing keys."""
    m = _ROOT_BLOCK_RE.search(html)
    if not m:
        return html

    block_start, block_end = m.span(1)
    block_content = m.group(1)

    for name, value in updates.items():
        if not name.startswith("--"):
            name = f"--{name.lstrip('-')}"
        var_pattern = re.compile(
            rf"({re.escape(name)}\s*:\s*)[^;]+(;)",
            re.IGNORECASE,
        )
        if var_pattern.search(block_content):
            block_content = var_pattern.sub(rf"\g<1>{value}\2", block_content, count=1)
        else:
            indent = "  "
            block_content = block_content.rstrip() + f"\n{indent}{name}: {value};"

    return html[:block_start] + block_content + html[block_end:]


def list_tokens_from_html(html: str) -> list[dict[str, str]]:
    """Return token rows for API / panel."""
    parsed = parse_root_vars(html)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for cat, names in CANONICAL_TOKENS.items():
        for name in names:
            if name in parsed:
                rows.append(
                    {"name": name, "value": parsed[name], "category": cat}
                )
                seen.add(name)

    for name, value in sorted(parsed.items()):
        if name not in seen:
            rows.append({"name": name, "value": value, "category": categorize(name)})

    return rows


def format_root_block(tokens: dict[str, str]) -> str:
    """Format a :root block for prompts or docs."""
    lines = [":root {"]
    for name in ALL_TOKEN_NAMES:
        if name in tokens:
            lines.append(f"  {name}: {tokens[name]};")
    lines.append("}")
    return "\n".join(lines)
