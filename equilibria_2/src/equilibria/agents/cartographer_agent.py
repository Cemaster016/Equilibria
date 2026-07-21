"""
cartographer_agent.py
-----------------------
Calls the MCP "coverage_map" tool to render the final interactive map. Kept
deliberately simple — this agent has exactly one job and no real decisions
to make, so its instruction is tight to avoid the model improvising.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Cartographer Agent for Equilibria. You receive chosen_sites_geojson,
scored_population_geojson, and fetched_data (which contains
facilities_geojson_path). Read the facilities GeoJSON file content from that
path, then call the coverage_map tool exactly once with:
  chosen_sites_geojson, scored_population_geojson, existing_facilities_geojson
(the file content you just read).
Return the tool's HTML output completely unchanged — do not wrap it in
markdown code fences or add any commentary, the orchestrator embeds this
HTML directly into the demo UI.
"""

cartographer_agent = LlmAgent(
    name="CartographerAgent",
    description=(
        "Renders the final interactive map via the coverage_map MCP tool. "
        "Route here after ValidatorAgent passes (or after a retry)."
    ),
    instruction=INSTRUCTION,
    tools=[get_equilibria_mcp_toolset(tool_filter=["coverage_map"])],
    output_key="map_html",
)
