"""MCP tools package (split from monolithic tools.py)."""

from .handlers import (
    TOOL_HANDLERS,
    compare_to_target,
    run_fidelity_comparison,
)
from .schema_mcp import TOOL_NAMES, create_tool_server
from .state import SERVER_NAME, get_fidelity_profile, set_fidelity_profile, set_notify_fn

__all__ = [
    "SERVER_NAME",
    "TOOL_HANDLERS",
    "TOOL_NAMES",
    "compare_to_target",
    "create_tool_server",
    "get_fidelity_profile",
    "run_fidelity_comparison",
    "set_fidelity_profile",
    "set_notify_fn",
]
