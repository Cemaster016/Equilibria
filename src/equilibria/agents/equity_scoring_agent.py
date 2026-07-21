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

from equilibria.agents.config import DEFAULT_MODEL
from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Equity-Scoring Agent for Equilibria. Session state contains:
  - fetched_data.population_geojson_path  (local file path)
  - fetched_data.facilities_geojson_path  (local file path)
  - fetched_data.road_graph_path          (local file path)
  - intake_result.equity_weight_hints     (optional: density/distance/road_access 0-1 floats)

Call the equity_score tool EXACTLY ONCE with:
  pop_geojson_path      = fetched_data.population_geojson_path
  facilities_geojson_path = fetched_data.facilities_geojson_path
  road_graph_path       = fetched_data.road_graph_path
  density_weight / distance_weight / road_access_weight = from equity_weight_hints if provided
    (they must sum to 1.0; proportionally rescale if they don't)

Do NOT read any files yourself — the tool reads them from disk.
Report back the file path returned by the tool, unchanged, with no extra text.
"""

equity_scoring_agent = LlmAgent(
    name="EquityScoringAgent",
    model=DEFAULT_MODEL,
    description=(
        "Scores a population grid by how underserved each cell is, using the "
        "equity_score MCP tool. Route here after DataFetcherAgent succeeds."
    ),
    instruction=INSTRUCTION,
    tools=[get_equilibria_mcp_toolset(tool_filter=["equity_score"])],
    output_key="scored_population_geojson",
)
