"""Website builder MCP tools for the Claude Agent SDK.

Write plain async functions with type hints and docstrings.
Tool schemas are auto-generated from function signatures.

To add a new tool: write an async function, add it to TOOL_HANDLERS.
"""

import inspect
import json
import re
import types
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

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


# Registry — add new tool functions here
TOOL_HANDLERS = [write_html, read_html]
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
                return {"content": [{"type": "text", "text": str(result)}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return handler


def create_tool_server():
    """Create a fresh MCP server instance."""
    return WebsiteToolServer().server
