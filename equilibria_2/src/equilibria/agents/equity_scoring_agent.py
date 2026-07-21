"""
equity_scoring_agent.py
------------------------
Calls the MCP "equity_score" tool with the data the DataFetcherAgent just
fetched, plus any weight hints from the IntakeAgent. The actual scoring math
runs inside the MCP server (spatial_tools.equity_score) — this agent's job
is just to read GeoJSON off disk, call the tool correctly, and pass the
result onward.
"""

from __future__ import annotations

import json
from pathlib import Path

from google.adk.agents import LlmAgent

from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Equity-Scoring Agent for Equilibria. You receive:
  - fetched_data: paths to population_geojson_path, road_graph_path, facilities_geojson_path
  - intake_result: may contain equity_weight_hints (density/distance/road_access, each 0-1)

Read the population and facilities GeoJSON files from their paths and pass
their raw text content as pop_geojson and facilities_geojson to the
equity_score tool, along with road_graph_path as given. If
equity_weight_hints are provided and any of density/distance/road_access is
set, use those values for density_weight/distance_weight/road_access_weight
(they must sum to 1.0 — if they don't, proportionally rescale them rather
than failing). If no hints are given, use the tool's defaults by omitting
those parameters.

Call the equity_score tool exactly once. Report back the returned GeoJSON
string unchanged — do not summarize or truncate it, the next agent needs
the full data.
"""

equity_scoring_agent = LlmAgent(
    name="EquityScoringAgent",
    description=(
        "Scores a population grid by how underserved each cell is, using the "
        "equity_score MCP tool. Route here after DataFetcherAgent succeeds."
    ),
    instruction=INSTRUCTION,
    tools=[get_equilibria_mcp_toolset(tool_filter=["equity_score"])],
    output_key="scored_population_geojson",
)
