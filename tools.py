"""Website builder MCP tools for the Claude Agent SDK.

Write plain async functions with type hints and docstrings.
Tool schemas are auto-generated from function signatures.

To add a new tool: write an async function, add it to TOOL_HANDLERS.
"""

import base64
import inspect
import io
import json
import re
import types
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from PIL import Image

from assets import extract_assets_url, load_manifest
from browser import CaptureResult, capture_compare, capture_file, capture_url, friendly_capture_error
from history import save_output
from compare import (
    DEFAULT_PROFILE,
    diff_heatmap,
    fidelity_report,
    load_config,
    resolve_profile,
)
from sections import list_sections, replace_section
from tokens import (
    extract_tokens_from_styles,
    format_root_block,
    list_tokens_from_html,
    parse_root_vars,
    patch_root_vars,
)

SERVER_NAME = "builder"

# Optional SSE notify callback (set by server.py)
_notify_fn = None


def set_notify_fn(fn):
    global _notify_fn
    _notify_fn = fn


def _notify(event="update"):
    if _notify_fn:
        _notify_fn(event)


# ---------------------------------------------------------------------------
# Schema generation (from function signatures + docstrings)
# ---------------------------------------------------------------------------


def _python_type_to_json_type(py_type: type) -> str:
    if py_type is str:
        return "string"
    elif py_type is int:
        return "integer"
    elif py_type is float:
        return "number"
    elif py_type is bool:
        return "boolean"
    return "string"


def _get_base_type(hint: Any) -> type:
    if hint is None:
        return str
    import typing
    origin = get_origin(hint)
    # Handle X | Y syntax and typing.Union / typing.Optional
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in get_args(hint) if a is not type(None)]
        return _get_base_type(args[0]) if args else str
    if isinstance(hint, type):
        return hint
    return str


def _parse_docstring_args(docstring: str | None) -> dict[str, str]:
    if not docstring:
        return {}
    result = {}
    in_args = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            continue
        if in_args and stripped in ("Returns:", "Raises:", "Yields:", "Note:"):
            break
        if in_args and stripped:
            match = re.match(r"^(\w+)(?:\s*\([^)]+\))?:\s*(.+)$", stripped)
            if match:
                result[match.group(1)] = match.group(2)
    return result


def _generate_tool_definition(fn) -> dict[str, Any]:
    """Generate a tool definition from a function's signature and docstring."""
    sig = inspect.signature(fn)
    type_hints = get_type_hints(fn)
    docstring_args = _parse_docstring_args(fn.__doc__)

    properties = {}
    required = []

    for name, param in sig.parameters.items():
        base_type = _get_base_type(type_hints.get(name))
        prop: dict[str, Any] = {"type": _python_type_to_json_type(base_type)}
        desc = docstring_args.get(name, "")
        if desc:
            prop["description"] = desc
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = ""
    if fn.__doc__:
        doc_lines = []
        for line in fn.__doc__.strip().split("\n"):
            if line.strip() in ("Args:", "Returns:", "Raises:"):
                break
            doc_lines.append(line.rstrip())
        description = "\n".join(doc_lines).strip()

    return {
        "name": fn.__name__,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ---------------------------------------------------------------------------
# Tool handler functions
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"

_target_cache: dict[str, CaptureResult] = {}
_asset_manifest_cache: dict[str, dict] = {}
_session_profile: str = DEFAULT_PROFILE


def set_fidelity_profile(profile: str | None) -> str:
    """Set the active fidelity profile for this agent run (called from server.py)."""
    global _session_profile
    _session_profile = resolve_profile(profile)
    return _session_profile


def get_fidelity_profile() -> str:
    return _session_profile


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u


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


def _normalize_tool_result(result: Any) -> dict:
    """Pass through structured MCP content blocks or wrap plain text."""
    if isinstance(result, dict) and "content" in result:
        return result
    if isinstance(result, list):
        return {"content": result}
    return {"content": [{"type": "text", "text": str(result)}]}


# Claude Agent SDK JSON lines default to a 1 MiB read buffer; keep embedded images small.
_MCP_IMAGE_BUDGET_BYTES = 600_000
_MCP_IMAGE_MAX_WIDTH = 960


def _encode_image_for_mcp(path: Path, *, max_width: int = _MCP_IMAGE_MAX_WIDTH) -> tuple[str, str]:
    """Downscale and JPEG-compress a screenshot for MCP transport."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize(
                (max_width, max(1, int(img.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        quality = 82
        while quality >= 45:
            buf.seek(0)
            buf.truncate(0)
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= 140_000:
                break
            quality -= 12
            if quality < 45 and img.width > 480:
                img = img.resize(
                    (max(480, img.width // 2), max(1, img.height // 2)),
                    Image.Resampling.LANCZOS,
                )
                quality = 82
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return data, "image/jpeg"


def _paths_to_image_blocks(paths: list[Path]) -> list[dict]:
    blocks: list[dict] = []
    budget = _MCP_IMAGE_BUDGET_BYTES
    omitted: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data, mime = _encode_image_for_mcp(path)
        except OSError:
            omitted.append(str(path))
            continue
        if len(data) > budget:
            omitted.append(str(path))
            continue
        blocks.append({"type": "image", "data": data, "mimeType": mime})
        budget -= len(data)
    if omitted:
        blocks.append(
            {
                "type": "text",
                "text": (
                    "Additional full-resolution tiles saved on disk (not embedded): "
                    + ", ".join(omitted)
                ),
            }
        )
    return blocks


def _capture_to_content(result: CaptureResult, label: str) -> dict:
    """Build MCP tool result with text, optional styles JSON, and image blocks."""
    content: list[dict] = []

    if result.dom_only:
        content.append(
            {
                "type": "text",
                "text": (
                    f"{label} — DOM-only fallback (screenshot failed).\n"
                    f"Error: {friendly_capture_error(result.error)}\n"
                    "Use the style JSON and text outline below. Do not guess colors from memory."
                ),
            }
        )
    elif result.paths:
        paths_str = ", ".join(str(p) for p in result.paths)
        content.append(
            {
                "type": "text",
                "text": (
                    f"{label} — {len(result.paths)} screenshot tile(s), top to bottom.\n"
                    f"Saved to: {paths_str}"
                ),
            }
        )
    else:
        content.append({"type": "text", "text": f"{label} — no screenshots captured."})

    if result.styles is not None:
        content.append(
            {
                "type": "text",
                "text": "Extracted styles (JSON):\n" + json.dumps(result.styles, indent=2),
            }
        )

    content.extend(_paths_to_image_blocks(result.paths))
    return {"content": content}


async def capture_site(url: str):
    """Capture a target website: tiled screenshots plus extracted design styles.

    Call this first when the user gives a URL. Returns PNG image tiles the model
    can see, plus a JSON summary of colors, fonts, and layout.

    Args:
        url: Public HTTP(S) URL of the site to copy
    """
    result = await capture_url(url)
    return _capture_to_content(result, f"Screenshot of {result.source or url}")


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
    return _capture_to_content(result, "Screenshot of current output (output/index.html)")


async def extract_assets(url: str):
    """Mirror page assets (images, computed backgrounds, inline SVG, fonts) to output/assets/.

    Call after capture_site when profile is more_faithful. Returns manifest JSON with
    preview_path (/assets/...), inline SVG files, and font_faces CSS snippets.

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

    _asset_manifest_cache[normalized] = result.manifest
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Downloaded {result.downloaded} asset(s) to output/assets/.\n"
                    "Manifest (use preview_path in HTML):\n"
                    + json.dumps(result.manifest, indent=2)
                ),
            }
        ]
    }


def _manifest_for_url(url: str) -> dict | None:
    normalized = _normalize_url(url)
    if normalized in _asset_manifest_cache:
        return _asset_manifest_cache[normalized]
    manifest = load_manifest()
    if manifest and manifest.get("source", "").rstrip("/") == normalized.rstrip("/"):
        _asset_manifest_cache[normalized] = manifest
        return manifest
    return None


def _shot_urls(paths: list[Path]) -> list[str]:
    return [f"/shots/{p.name}" for p in paths if p.is_file()]


async def run_fidelity_comparison(
    url: str, profile: str | None = None
) -> dict[str, Any]:
    """Run Phase 2 fidelity compare; shared by compare_to_target and POST /compare."""
    prof = resolve_profile(profile or _session_profile)
    normalized = _normalize_url(url)

    target = _target_cache.get(normalized)
    if target is None or target.compare_payload is None:
        target = await capture_compare(normalized, is_file=False)
        _target_cache[normalized] = target

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


async def compare_to_target(url: str, profile: str | None = None):
    """Compare output/index.html to the target URL with a fidelity report.

    Returns per-axis scores (content, structure, layout, visual), a weighted
    total, verdict (pass/warn/fail), gate failures, and worst sections to fix.
    Call after write_html during the self-check loop.

    Args:
        url: Target site URL (same URL used in capture_site)
        profile: Fidelity knob — more_editable, balanced (default), or more_faithful
    """
    prof = resolve_profile(profile or _session_profile)
    result = await run_fidelity_comparison(url, profile=prof)

    if result.get("error"):
        msg = result["error"]
        if result.get("detail"):
            msg += " " + result["detail"]
        return {"content": [{"type": "text", "text": msg}]}

    report = result["report"]
    prof = result.get("profile", prof)

    # Phase 6: log this self-check as one convergence round, then nudge the UI.
    import convergence
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
    heatmap = result.get("heatmap")
    if heatmap:
        heatmap_path = Path("output") / ".shots" / Path(heatmap).name
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


async def extract_design_tokens(url: str):
    """Extract canonical design tokens from a target URL's computed styles.

    Call after capture_site to seed the :root block in write_html. Returns JSON
    token names and values (colors, fonts, radius, shadow, spacing).

    Args:
        url: Target site URL (same as capture_site)
    """
    normalized = _normalize_url(url)
    if normalized not in _target_cache:
        _target_cache[normalized] = await capture_url(normalized)
    result = _target_cache[normalized]
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


# Registry — add new tool functions here
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
TOOL_NAMES = [fn.__name__ for fn in TOOL_HANDLERS]


# ---------------------------------------------------------------------------
# MCP server creation
# ---------------------------------------------------------------------------


class WebsiteToolServer:
    def __init__(self):
        from claude_agent_sdk import create_sdk_mcp_server
        self._server = create_sdk_mcp_server(
            name=SERVER_NAME, version="1.0.0", tools=self._build_tools(),
        )

    @property
    def server(self):
        return self._server

    def _build_tools(self):
        from claude_agent_sdk import tool as sdk_tool
        tools = []
        for fn in TOOL_HANDLERS:
            defn = _generate_tool_definition(fn)
            handler = self._make_handler(fn)
            decorated = sdk_tool(
                defn["name"], defn["description"], defn["input_schema"],
            )(handler)
            tools.append(decorated)
        return tools

    def _make_handler(self, fn):
        async def handler(args: dict) -> dict:
            try:
                result = await fn(**args)
                return _normalize_tool_result(result)
            except Exception as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return handler


def create_tool_server():
    """Create a fresh MCP server instance."""
    return WebsiteToolServer().server
