"""
site_optimizer_agent.py
-------------------------
Generates candidate facility locations from the road network, then calls the
MCP "site_allocate" tool to pick the best `num_sites` of them under any
budget constraint from intake. Two MCP tool calls, in a fixed order — this
agent's instruction is deliberately strict because getting the call order
wrong (allocating before generating candidates) would silently produce
garbage results.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from equilibria.agents.config import DEFAULT_MODEL
from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Site-Optimizer Agent for Equilibria. Session state contains:
  - fetched_data.road_graph_path          (local file path)
  - scored_population_geojson             (local file path to scored population GeoJSON)
  - intake_result.num_sites, .budget_per_site, .total_budget

Steps, IN THIS ORDER:
1. Call generate_candidate_sites with road_graph_path from fetched_data.
2. Call site_allocate with:
     candidate_points_geojson       = the GeoJSON string returned by step 1
     scored_population_geojson_path = the value of scored_population_geojson (it is a file path)
     k                              = intake_result.num_sites
     budget_per_site                = intake_result.budget_per_site (omit if null)
     total_budget                   = intake_result.total_budget (omit if null)

If site_allocate returns an error (no candidates cover any population),
report it clearly — do not invent results.
Return the chosen-sites GeoJSON string from site_allocate unchanged.
"""

site_optimizer_agent = LlmAgent(
    name="SiteOptimizerAgent",
    model=DEFAULT_MODEL,
    description=(
        "Generates candidate sites from the road network and selects the best "
        "ones via the site_allocate MCP tool. Route here after EquityScoringAgent."
    ),
    instruction=INSTRUCTION,
    tools=[
        get_equilibria_mcp_toolset(tool_filter=["generate_candidate_sites", "site_allocate"])
    ],
    output_key="chosen_sites_geojson",
)
