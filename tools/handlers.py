"""Aggregate MCP tool callables for schema generation."""

from __future__ import annotations

from .handlers_capture import capture_site, extract_assets, screenshot_output
from .handlers_fidelity import compare_to_target, run_fidelity_comparison
from .handlers_html import edit_section, read_html, write_html
from .handlers_tokens import extract_design_tokens, read_design_tokens, set_design_token

TOOL_HANDLERS = [
    write_html,
    read_html,
    edit_section,
    capture_site,
    screenshot_output,
    extract_assets,
    extract_design_tokens,
    read_design_tokens,
    set_design_token,
    compare_to_target,
]

__all__ = [
    "TOOL_HANDLERS",
    "compare_to_target",
    "run_fidelity_comparison",
]
