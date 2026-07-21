"""
data_fetcher_agent.py
----------------------
Resolves a place name to a bounding box, then fetches population, road
network, and existing-facility data for that area using the data_layer
modules. Wrapped as a single FunctionTool so the LLM's only real decision is
"call this tool with the location name" — the actual data engineering is
deterministic Python, not left to the model's judgement.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from equilibria.data_layer.population import fetch_population_grid, population_to_geodataframe
from equilibria.data_layer.roads import fetch_road_network
from equilibria.data_layer.facilities import fetch_existing_facilities

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(os.getenv("EQUILIBRIA_PROCESSED_DATA_DIR", "data/processed"))


class FetchedDataPaths(BaseModel):
    bbox: tuple[float, float, float, float] = Field(description="(minx, miny, maxx, maxy) in EPSG:4326")
    population_geojson_path: str
    road_graph_path: str
    facilities_geojson_path: str
    error: Optional[str] = Field(default=None)


def fetch_area_data(
    location_name: str,
    country_iso3: str = "NGA",
    facility_source: str = "osm",
) -> dict:
    """
    Geocodes `location_name`, then fetches and caches population, road
    network, and facility data for that area. Returns file paths rather than
    raw data so this stays cheap to pass through agent context.
    """
    from geopy.geocoders import Nominatim

    geolocator = Nominatim(user_agent="equilibria-siting-agent")
    location = geolocator.geocode(location_name)
    if location is None:
        return FetchedDataPaths(
            bbox=(0, 0, 0, 0),
            population_geojson_path="",
            road_graph_path="",
            facilities_geojson_path="",
            error=f"Could not geocode '{location_name}'. Try a more specific or differently spelled place name.",
        ).model_dump()

    # geopy gives a point, not a bbox; build a ~15km buffer box around it.
    # (For production this should use Nominatim's bounding box extras when available.)
    buffer_deg = 0.135  # ~15km at the equator
    bbox = (
        location.longitude - buffer_deg,
        location.latitude - buffer_deg,
        location.longitude + buffer_deg,
        location.latitude + buffer_deg,
    )

    out_dir = PROCESSED_DIR / location_name.lower().replace(" ", "_").replace(",", "")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        raster = fetch_population_grid(bbox, country_iso3=country_iso3)
        pop_gdf = population_to_geodataframe(raster)
        pop_path = out_dir / "population.geojson"
        pop_gdf.to_file(pop_path, driver="GeoJSON")

        road_graph = fetch_road_network(bbox, network_type="drive")
        import osmnx as ox

        road_path = out_dir / "roads.graphml"
        ox.save_graphml(road_graph, road_path)

        facilities_gdf = fetch_existing_facilities(bbox, source=facility_source)
        facilities_path = out_dir / "facilities.geojson"
        facilities_gdf.to_file(facilities_path, driver="GeoJSON")
    except Exception as exc:  # surface a clean error to the orchestrator instead of crashing
        logger.exception("fetch_area_data failed for %s", location_name)
        return FetchedDataPaths(
            bbox=bbox,
            population_geojson_path="",
            road_graph_path="",
            facilities_geojson_path="",
            error=str(exc),
        ).model_dump()

    return FetchedDataPaths(
        bbox=bbox,
        population_geojson_path=str(pop_path),
        road_graph_path=str(road_path),
        facilities_geojson_path=str(facilities_path),
    ).model_dump()


fetch_area_data_tool = FunctionTool(fetch_area_data)

INSTRUCTION = """\
You are the Data-Fetcher Agent for Equilibria. You receive a resolved
location_name from the intake step. Call the fetch_area_data tool EXACTLY
ONCE with that location_name (use country_iso3="NGA" unless the location is
clearly outside Nigeria). Then report back the returned paths and bbox
exactly as given — do not summarize, alter, or omit the 'error' field if
present; if 'error' is set, clearly state that data fetching failed and
include the error message verbatim so the orchestrator can decide whether to
retry or ask the user for a different location.
"""

data_fetcher_agent = LlmAgent(
    name="DataFetcherAgent",
    description=(
        "Geocodes a location and fetches population, road, and facility data "
        "for it. Route here after IntakeAgent has resolved a location_name."
    ),
    instruction=INSTRUCTION,
    tools=[fetch_area_data_tool],
    output_key="fetched_data",
)
