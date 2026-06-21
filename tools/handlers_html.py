"""MCP tools: read/write full HTML and section edits."""

from __future__ import annotations

from builder_config import OUTPUT_FILE
from history import save_output
from sections import list_sections, replace_section

from .state import _notify


async def write_html(html: str):
    """Write HTML/CSS to the preview. The result renders live in the viewer.

    Write a complete HTML document including <!DOCTYPE html>, <head>, and <body>.

    Args:
        html: Complete HTML document source
    """
    save_output(html, "write_html")
    _notify("html_updated")
    return f"HTML written ({len(html)} chars). Preview updated."


async def read_html() -> str:
    """Read the current HTML source."""
    if OUTPUT_FILE.exists():
        return OUTPUT_FILE.read_text()
    return ""


async def edit_section(selector: str, html: str):
    """Replace one page section without rewriting the full document.

    Targets the first element matching selector (data-section name, #id, or tag).
    Use after initial write_html; prefer this for "change the hero" style edits.

    Args:
        selector: Section id, e.g. hero, footer, or CSS selector [data-section="hero"]
        html: New HTML fragment for that section (not a full document)
    """
    if not OUTPUT_FILE.is_file():
        return "No output/index.html yet. Call write_html first."

    source = OUTPUT_FILE.read_text()
    updated, matched = replace_section(source, selector, html)
    if not matched:
        available = list_sections(source)
        names = ", ".join(s["selector"] for s in available) or "none"
        return (
            f"Section '{selector}' not found. Available data-section anchors: {names}"
        )

    save_output(updated, f"edit-{selector}")
    _notify("html_updated")
    return f"Section '{selector}' updated ({len(html)} chars). Preview refreshed."
