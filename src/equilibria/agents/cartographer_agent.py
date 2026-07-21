"""
cartographer_agent.py
-----------------------
Calls the MCP "coverage_map" tool to render the final interactive map. Kept
deliberately simple — this agent has exactly one job and no real decisions
to make, so its instruction is tight to avoid the model improvising.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from equilibria.agents.config import DEFAULT_MODEL
from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Cartographer Agent for Equilibria. Session state contains:
  - chosen_sites_geojson              (GeoJSON STRING — direct output of site_allocate)
  - scored_population_geojson         (local file path to the scored population GeoJSON)
  - fetched_data.facilities_geojson_path (local file path)

Call the coverage_map tool EXACTLY ONCE with:
  chosen_sites_geojson             = the chosen_sites_geojson string
  scored_population_geojson_path   = the scored_population_geojson value (it is a file path)
  existing_facilities_geojson_path = fetched_data.facilities_geojson_path

Do NOT read any files yourself — the tool reads them from disk.
Return the HTML string from the tool completely unchanged — no markdown fences,
no commentary. The orchestrator embeds this HTML directly into the demo UI.
"""

cartographer_agent = LlmAgent(
    name="CartographerAgent",
    model=DEFAULT_MODEL,
    description=(
        "Renders the final interactive map via the coverage_map MCP tool. "
        "Route here after ValidatorAgent passes (or after a retry)."
    ),
    instruction=INSTRUCTION,
    tools=[get_equilibria_mcp_toolset(tool_filter=["coverage_map"])],
    output_key="map_html",
)
