"""
server.py
---------
Wraps the pure functions in spatial_tools.py as MCP tools using FastMCP, so
any MCP-compatible agent (Equilibria's own ADK orchestrator, or Claude
Desktop / Gemini directly) can call them by name.

All tool inputs/outputs that carry geometry are passed as GeoJSON strings,
since that's the lowest-common-denominator format every agent platform can
read and write without needing geopandas installed on the caller's side.

Run standalone (e.g. for testing with the MCP Inspector) via:
    python -m equilibria.mcp_server.server
"""

from __future__ import annotations

import json
import logging

import geopandas as gpd
from mcp.server.fastmcp import FastMCP

from equilibria.mcp_server import spatial_tools as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="equilibria-spatial-tools",
    instructions=(
        "Tools for equity-weighted facility siting analysis: scoring how "
        "underserved a population grid is, choosing optimal new facility "
        "sites under a budget, and rendering the result as an interactive map."
    ),
)


def _geojson_to_gdf(geojson_str: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame.from_features(json.loads(geojson_str)["features"], crs="EPSG:4326")


def _gdf_to_geojson(gdf: gpd.GeoDataFrame) -> str:
    return gdf.to_json()


@mcp.tool(
    description=(
        "Generates a list of plausible new-facility candidate locations from "
        "a cached road network's intersection nodes (roads must already be "
        "fetched and saved via the data layer). Returns candidates as a "
        "GeoJSON FeatureCollection of points. Run this BEFORE site_allocate "
        "to get a candidate_points_geojson input for it."
    )
)
def generate_candidate_sites(road_graph_path: str, max_candidates: int = 300) -> str:
    import osmnx as ox

    road_graph = ox.load_graphml(road_graph_path)
    result = st.candidate_sites_from_road_graph(road_graph, max_candidates=max_candidates)
    return _gdf_to_geojson(result)


@mcp.tool(
    description=(
        "Scores every cell in a population grid on how UNDERSERVED it is "
        "(0-100, higher = higher priority for a new facility), based on a "
        "weighted blend of population density, network distance to the "
        "nearest existing facility, and road-access poverty. Inputs are "
        "LOCAL FILE PATHS to GeoJSON files (not raw GeoJSON strings); the "
        "road network must already be cached for the same area. "
        "Saves the scored grid to {pop_geojson_path's directory}/scored_population.geojson "
        "and returns that file path as a string."
    )
)
def equity_score(
    pop_geojson_path: str,
    facilities_geojson_path: str,
    road_graph_path: str,
    density_weight: float = 0.4,
    distance_weight: float = 0.4,
    road_access_weight: float = 0.2,
) -> str:
    import osmnx as ox
    from pathlib import Path

    pop_gdf = gpd.read_file(pop_geojson_path)
    facilities_gdf = gpd.read_file(facilities_geojson_path)
    road_graph = ox.load_graphml(road_graph_path)

    weights = {
        "density": density_weight,
        "distance": distance_weight,
        "road_access": road_access_weight,
    }
    result = st.equity_score(pop_gdf, facilities_gdf, road_graph, weights=weights)
    out_path = Path(pop_geojson_path).parent / "scored_population.geojson"
    result.to_file(out_path, driver="GeoJSON")
    return str(out_path)


@mcp.tool(
    description=(
        "Chooses up to k new facility sites from a list of candidate "
        "locations to maximize equity-weighted population coverage, "
        "respecting an optional budget. Requires scored_population_geojson_path "
        "to point to a GeoJSON file that already has an 'equity_score' column "
        "(run the equity_score tool first). candidate_points_geojson is a "
        "small GeoJSON STRING (the direct output of generate_candidate_sites). "
        "Returns the chosen sites as a GeoJSON STRING with "
        "'population_covered' and 'cumulative_coverage_pct' columns added."
    )
)
def site_allocate(
    candidate_points_geojson: str,
    scored_population_geojson_path: str,
    k: int,
    budget_per_site: float | None = None,
    total_budget: float | None = None,
    service_radius_m: float = 5000.0,
) -> str:
    candidates_gdf = _geojson_to_gdf(candidate_points_geojson)
    pop_gdf = gpd.read_file(scored_population_geojson_path)

    result = st.site_allocate(
        candidates_gdf,
        pop_gdf,
        k=k,
        budget_per_site=budget_per_site,
        total_budget=total_budget,
        service_radius_m=service_radius_m,
    )
    return _gdf_to_geojson(result)


@mcp.tool(
    description=(
        "Renders an interactive HTML map showing the equity-score choropleth "
        "of the population grid, existing facilities (grey markers), and "
        "newly proposed sites (green star markers with coverage popups). "
        "chosen_sites_geojson is a small GeoJSON STRING (direct output of "
        "site_allocate). scored_population_geojson_path and "
        "existing_facilities_geojson_path are LOCAL FILE PATHS. "
        "Returns raw HTML as a string, ready to embed in a web page or "
        "Streamlit component."
    )
)
def coverage_map(
    chosen_sites_geojson: str,
    scored_population_geojson_path: str,
    existing_facilities_geojson_path: str,
) -> str:
    chosen_gdf = _geojson_to_gdf(chosen_sites_geojson)
    pop_gdf = gpd.read_file(scored_population_geojson_path)
    facilities_gdf = gpd.read_file(existing_facilities_geojson_path)

    folium_map = st.coverage_map(chosen_gdf, pop_gdf, facilities_gdf)
    return folium_map._repr_html_()


if __name__ == "__main__":
    logger.info("Starting Equilibria MCP server over stdio transport...")
    mcp.run(transport="stdio")
