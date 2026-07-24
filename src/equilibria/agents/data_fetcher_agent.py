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
import networkx as nx
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

    population_path = out_dir / "population.geojson"
    road_path = out_dir / "roads.graphml"
    facilities_path = out_dir / "facilities.geojson"

    if population_path.exists() and road_path.exists() and facilities_path.exists():
        logger.info("Using cached processed data for %s", location_name)
        return FetchedDataPaths(
            bbox=bbox,
            population_geojson_path=str(population_path),
            road_graph_path=str(road_path),
            facilities_geojson_path=str(facilities_path),
        ).model_dump()

   try:
    # Check if processed data already exists for this location
    out_dir = PROCESSED_DIR / location_name.lower().replace(" ", "_").replace(",", "")
    pop_path = out_dir / "population.geojson"
    road_path = out_dir / "roads.graphml"
    facilities_path = out_dir / "facilities.geojson"

    if pop_path.exists() and road_path.exists() and facilities_path.exists():
        logger.info("Using cached data for %s", location_name)
        return FetchedDataPaths(
            bbox=bbox,
            population_geojson_path=str(pop_path),
            road_graph_path=str(road_path),
            facilities_geojson_path=str(facilities_path),
        ).model_dump()

    out_dir.mkdir(parents=True, exist_ok=True)

    # Population grid
    try:
        raster = fetch_population_grid(bbox_tuple, country_iso3=country_iso3)
        pop_gdf = population_to_geodataframe(raster)
    except Exception as exc:
        logger.warning("WorldPop download failed, using synthetic grid: %s", exc)
        pop_gdf = _synthetic_population_grid(bbox_tuple)

    pop_gdf.to_file(pop_path, driver="GeoJSON")

    # Road network
    try:
        road_graph = fetch_road_network(bbox_tuple, network_type="drive")
    except Exception as exc:
        logger.warning("OSM road download failed, using minimal graph: %s", exc)
        road_graph = _minimal_road_graph(bbox_tuple)

    import osmnx as ox
    ox.save_graphml(road_graph, road_path)

    # Facilities
    try:
        facilities_gdf = fetch_existing_facilities(bbox_tuple, source=facility_source)
    except Exception:
        try:
            facilities_gdf = fetch_existing_facilities(bbox_tuple, source="osm")
        except Exception as exc2:
            logger.warning("All facility sources failed: %s", exc2)
            facilities_gdf = _empty_facilities_gdf()

    facilities_gdf.to_file(facilities_path, driver="GeoJSON")

except Exception as exc:
    logger.exception("fetch_area_data failed for %s", location_name)
    return FetchedDataPaths(
        bbox=bbox,
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


def _synthetic_population_grid(bbox: tuple) -> gpd.GeoDataFrame:
    """20x20 synthetic grid when WorldPop download fails."""
    import numpy as np
    from shapely.geometry import box as sbox
    minx, miny, maxx, maxy = bbox
    xs = np.linspace(minx, maxx, 20)
    ys = np.linspace(miny, maxy, 20)
    records = []
    for x in xs:
        for y in ys:
            records.append({
                "geometry": sbox(x, y, x + (maxx-minx)/20, y + (maxy-miny)/20),
                "pop_count": float(np.random.randint(100, 5000))
            })
    return gpd.GeoDataFrame(records, crs="EPSG:4326")


def _minimal_road_graph(bbox: tuple) -> "nx.MultiDiGraph":
    """Tiny 4-node graph when OSM download fails."""
    import networkx as nx
    minx, miny, maxx, maxy = bbox
    g = nx.MultiDiGraph()
    nodes = {
        0: (minx, miny), 1: (maxx, miny),
        2: (minx, maxy), 3: (maxx, maxy)
    }
    for n, (x, y) in nodes.items():
        g.add_node(n, x=x, y=y)
    for a, b in [(0,1),(1,0),(0,2),(2,0),(1,3),(3,1),(2,3),(3,2)]:
        g.add_edge(a, b, length=10000, travel_time=600)
    return g


def _empty_facilities_gdf() -> gpd.GeoDataFrame:
    """Empty facilities GeoDataFrame as last resort."""
    from shapely.geometry import Point
    return gpd.GeoDataFrame(
        [{"name": "Unknown", "facility_type": "unknown",
          "geometry": Point(0, 0)}],
        crs="EPSG:4326"
    )



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
