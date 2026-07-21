"""
roads.py
--------
Fetches a drivable/walkable OSM road network for a bounding box and provides
a network-distance helper used by the equity-scoring tool (Week 7 skillset —
this is the same "closest facility"/shortest-path logic from the Network
Analyst material, just running on free OSM data via osmnx/networkx instead
of ArcGIS).
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional

import networkx as nx
from shapely.geometry import Point

logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(os.getenv("EQUILIBRIA_RAW_DATA_DIR", "data/raw")) / "roads"

BBox = tuple[float, float, float, float]  # (minx, miny, maxx, maxy) in lon/lat


class RoadNetworkError(Exception):
    """Raised when no usable road network is returned for a bounding box."""


def _bbox_cache_key(bbox: BBox, network_type: str) -> str:
    return "roads_{}_{}_{}_{}_{}_{}.graphml".format(
        network_type, *[round(v, 4) for v in bbox]
    )


def fetch_road_network(
    bbox: BBox,
    network_type: str = "drive",
    *,
    cache_dir: Path = RAW_DATA_DIR,
) -> nx.MultiDiGraph:
    """
    Downloads (or reuses a cached copy of) the OSM road network inside `bbox`.

    Parameters
    ----------
    bbox : (minx, miny, maxx, maxy) in EPSG:4326
    network_type : "drive", "walk", or "bike" (passed straight to osmnx)
    """
    import osmnx as ox

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / _bbox_cache_key(bbox, network_type)

    if cache_path.exists():
        logger.info("Using cached road network: %s", cache_path)
        return ox.load_graphml(cache_path)

    minx, miny, maxx, maxy = bbox
    logger.info("Downloading OSM %s network for bbox=%s", network_type, bbox)
    try:
        graph = ox.graph_from_bbox((maxy, miny, maxx, minx), network_type=network_type)
    except TypeError:
        # osmnx>=2.0 changed the bbox argument order/shape across minor versions;
        # fall back to the (west, south, east, north) tuple form if needed.
        graph = ox.graph_from_bbox(bbox=(minx, miny, maxx, maxy), network_type=network_type)

    if graph.number_of_nodes() == 0:
        raise RoadNetworkError(
            f"OSM returned an empty road network for bbox={bbox}. "
            "Check the bounding box covers a populated area with mapped roads."
        )

    # Add travel time (seconds) as an edge weight for routing realism — falls
    # back to physical length only when a maxspeed tag is missing, which is
    # common on rural Nigerian OSM data.
    graph = ox.add_edge_speeds(graph)
    graph = ox.add_edge_travel_times(graph)

    ox.save_graphml(graph, cache_path)
    return graph


def nearest_facility_distance(
    graph: nx.MultiDiGraph,
    point: Point,
    facility_points: list[Point],
    weight: str = "travel_time",
) -> float:
    """
    Returns the shortest NETWORK distance/time (not straight-line) from `point`
    to the nearest of `facility_points`, in the units of `weight`
    ("travel_time" -> seconds, "length" -> metres).

    Falls back to "length" automatically if travel_time isn't present on the
    graph (e.g. when add_edge_travel_times wasn't run).
    """
    import osmnx as ox

    if weight == "travel_time" and not any(
        "travel_time" in data for _, _, data in graph.edges(data=True)
    ):
        weight = "length"

    if not facility_points:
        raise RoadNetworkError("nearest_facility_distance called with an empty facility list.")

    origin_node = ox.distance.nearest_nodes(graph, point.x, point.y)
    best: Optional[float] = None

    for fp in facility_points:
        dest_node = ox.distance.nearest_nodes(graph, fp.x, fp.y)
        try:
            dist = nx.shortest_path_length(graph, origin_node, dest_node, weight=weight)
        except nx.NetworkXNoPath:
            continue
        if best is None or dist < best:
            best = dist

    if best is None:
        raise RoadNetworkError(
            "No path found between the given point and any facility — "
            "the road graph may be disconnected for this bbox."
        )
    return best
