"""MCP tool schema generation and SDK server wrapper."""

from __future__ import annotations

import inspect
import re
import types
from typing import Any, get_args, get_origin, get_type_hints

from .handlers import TOOL_HANDLERS
from .mcp_media import normalize_tool_result
from .state import SERVER_NAME


def _python_type_to_json_type(py_type: type) -> str:
    if py_type is str:
        return "string"
    if py_type is int:
        return "integer"
    if py_type is float:
        return "number"
    if py_type is bool:
        return "boolean"
    return "string"


def _get_base_type(hint: Any) -> type:
    if hint is None:
        return str
    import typing

    origin = get_origin(hint)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in get_args(hint) if a is not type(None)]
        return _get_base_type(args[0]) if args else str
    if isinstance(hint, type):
        return hint
    return str


def _parse_docstring_args(docstring: str | None) -> dict[str, str]:
    if not docstring:
        return {}
    result: dict[str, str] = {}
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
                return normalize_tool_result(result)
            except Exception as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}

        return handler


def create_tool_server():
    return WebsiteToolServer().server


TOOL_NAMES = [fn.__name__ for fn in TOOL_HANDLERS]
