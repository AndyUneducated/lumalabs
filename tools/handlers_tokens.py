"""MCP tools: design tokens from capture and :root in output."""

from __future__ import annotations

import json

from browser import capture_url
from builder_config import OUTPUT_FILE
from history import save_output
from tokens import (
    extract_tokens_from_styles,
    format_root_block,
    list_tokens_from_html,
    parse_root_vars,
    patch_root_vars,
)

from .state import _normalize_url, get_target_cache, _notify


async def extract_design_tokens(url: str):
    """Extract canonical design tokens from a target URL's computed styles.

    Call after capture_site to seed the :root block in write_html. Returns JSON
    token names and values (colors, fonts, radius, shadow, spacing).

    Args:
        url: Target site URL (same as capture_site)
    """
    normalized = _normalize_url(url)
    tc = get_target_cache()
    if normalized not in tc:
        tc[normalized] = await capture_url(normalized)
    result = tc[normalized]
    tokens = extract_tokens_from_styles(result.styles)
    payload = {
        "source": normalized,
        "tokens": tokens,
        "root_block": format_root_block(tokens),
        "dom_only": result.dom_only,
    }
    if result.error:
        payload["capture_error"] = result.error
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "Design tokens extracted from computed styles.\n"
                    "Use these values in a single :root { } block and reference "
                    "var(--token) everywhere:\n"
                    + json.dumps(payload, indent=2)
                ),
            }
        ]
    }


async def read_design_tokens():
    """Read CSS custom properties from the current output :root block.

    Returns parsed token name/value pairs for rebrand or inspection.
    """
    if not OUTPUT_FILE.is_file():
        return "No output/index.html yet. Call write_html first."
    html = OUTPUT_FILE.read_text()
    rows = list_tokens_from_html(html)
    if not rows:
        return "No :root CSS variables found in output/index.html."
    return json.dumps({"tokens": rows}, indent=2)


async def set_design_token(name: str, value: str):
    """Update one CSS variable in the :root block without rewriting the page.

    Args:
        name: Token name, e.g. --color-brand
        value: New value, e.g. #7c3aed
    """
    if not OUTPUT_FILE.is_file():
        return "No output/index.html yet. Call write_html first."
    if not name.startswith("--"):
        name = f"--{name.lstrip('-')}"
    html = OUTPUT_FILE.read_text()
    if not parse_root_vars(html):
        return "No :root block in output/index.html. Author tokens during write_html first."
    patched = patch_root_vars(html, {name: value})
    save_output(patched, f"token-{name.lstrip('-')}")
    _notify("html_updated")
    return f"Updated {name} = {value}. Preview refreshed."
