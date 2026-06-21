"""MCP tools: capture target site, preview screenshots, asset mirroring."""

from __future__ import annotations

import json

from assets import extract_assets_url
from browser import capture_file, capture_url, friendly_capture_error
from builder_config import OUTPUT_FILE

from .mcp_media import capture_to_content
from .state import _normalize_url, get_asset_manifest_cache, _notify


async def capture_site(url: str):
    """Capture a target website: tiled screenshots plus extracted design styles.

    Call this first when the user gives a URL. Returns PNG image tiles the model
    can see, plus a JSON summary of colors, fonts, and layout.

    Args:
        url: Public HTTP(S) URL of the site to copy
    """
    result = await capture_url(url)
    return capture_to_content(result, f"Screenshot of {result.source or url}")


async def screenshot_output():
    """Screenshot the current HTML preview (output/index.html) for self-check.

    Call after write_html to compare your output against the target screenshot.
    Returns PNG image tiles of the live preview.
    """
    result = await capture_file(OUTPUT_FILE)
    if result.dom_only and result.error and "not found" in (result.error or "").lower():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "No output/index.html yet. Call write_html first, then screenshot_output.",
                }
            ]
        }
    return capture_to_content(result, "Screenshot of current output (output/index.html)")


async def extract_assets(url: str):
    """Mirror page assets (images, computed backgrounds, inline SVG, fonts) to output/assets/.

    Call after capture_site when profile is more_faithful. Scrolls the page first to surface
    lazy-loaded media. Returns manifest JSON: `files` (all mirrors), `hints.clone_paths_ordered`,
    `preview_path` (/assets/...), inline SVG files, and font_faces CSS snippets.

    Args:
        url: Target site URL
    """
    normalized = _normalize_url(url)
    result = await extract_assets_url(normalized)
    if result.error and not result.downloaded:
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Asset extract failed for {normalized}: "
                        f"{friendly_capture_error(result.error)}\n"
                        "Fall back to capture_site styles only."
                    ),
                }
            ]
        }

    get_asset_manifest_cache()[normalized] = result.manifest
    hints = result.manifest.get("hints") or {}
    n_files = len(result.manifest.get("files") or [])
    clone_n = len(hints.get("clone_paths_ordered") or [])
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Downloaded {result.downloaded} asset(s) to output/assets/.\n"
                    "For maximum visual match, reference **every** `files[].preview_path` in your HTML/CSS "
                    f"({n_files} mirrored URLs). `hints.clone_paths_ordered` lists {clone_n} paths top-to-bottom.\n"
                    "Manifest (JSON):\n"
                    + json.dumps(result.manifest, indent=2)
                ),
            }
        ]
    }
