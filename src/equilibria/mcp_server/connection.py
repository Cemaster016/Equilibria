"""
connection.py
-------------
Shared helper for ADK agents that need to call the Equilibria MCP server.
Centralizing this means every agent connects the same way, and if the
transport ever changes (e.g. stdio -> streamable HTTP for a deployed
version), it only needs updating here.
"""

from __future__ import annotations

import sys

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StdioServerParameters


def get_equilibria_mcp_toolset(tool_filter: list[str] | None = None) -> McpToolset:
    """
    Returns an McpToolset wired to launch the Equilibria spatial-tools MCP
    server as a subprocess over stdio. `tool_filter` restricts which tools
    are exposed to the calling agent (e.g. ["equity_score"] for the
    EquityScoringAgent), so each agent only sees the tool(s) relevant to its job.
    """
    connection_params = StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "equilibria.mcp_server.server"],
        ),
        timeout=120,
    )
    return McpToolset(connection_params=connection_params, tool_filter=tool_filter)
