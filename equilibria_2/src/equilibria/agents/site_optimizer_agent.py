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

from equilibria.mcp_server.connection import get_equilibria_mcp_toolset

INSTRUCTION = """\
You are the Site-Optimizer Agent for Equilibria. You receive:
  - fetched_data: contains road_graph_path
  - scored_population_geojson: the population grid with equity_score already added
  - intake_result: contains num_sites, budget_per_site, total_budget

Steps, IN THIS ORDER:
1. Call generate_candidate_sites with road_graph_path to get candidate locations.
2. Call site_allocate with:
     candidate_points_geojson = the result of step 1
     scored_population_geojson = the value already provided to you
     k = intake_result.num_sites
     budget_per_site = intake_result.budget_per_site (or omit if null)
     total_budget = intake_result.total_budget (or omit if null)

If site_allocate returns an error because no candidate covers any
population, report that clearly rather than inventing a result — this
usually means the bounding box for this location was too small or the
service_radius_m default (5000m) doesn't fit a rural area, and the
orchestrator may want to retry with a larger service_radius_m.

Report back the final chosen-sites GeoJSON unchanged.
"""

site_optimizer_agent = LlmAgent(
    name="SiteOptimizerAgent",
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
