"""Website builder MCP tools for the Claude Agent SDK.

Write plain async functions with type hints and docstrings.
Tool schemas are auto-generated from function signatures.

To add a new tool: write an async function, add it to TOOL_HANDLERS.
"""

import base64
import inspect
import json
import re
import types
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from browser import CaptureResult, capture_file, capture_url

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


async def write_html(html: str):
    """Write HTML/CSS to the preview. The result renders live in the viewer.

    Write a complete HTML document including <!DOCTYPE html>, <head>, and <body>.

    Args:
        html: Complete HTML document source
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html)
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


def _paths_to_image_blocks(paths: list[Path]) -> list[dict]:
    blocks = []
    for path in paths:
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        blocks.append({"type": "image", "data": data, "mimeType": "image/png"})
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
                    f"Error: {result.error or 'unknown'}\n"
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


# Registry — add new tool functions here
TOOL_HANDLERS = [write_html, read_html, capture_site, screenshot_output]
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
