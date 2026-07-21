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

import logging
import math
import os
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import Point

ox.settings.timeout = 180          # 3 minutes instead of default 30s
ox.settings.max_query_area_size = 25_000_000_000  # allow larger bboxes

logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(os.getenv("EQUILIBRIA_RAW_DATA_DIR", "data/raw")) / "roads"

BBox = tuple[float, float, float, float]  # (minx, miny, maxx, maxy) in lon/lat

# Overpass API mirrors tried in order; first reachable one wins.
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
_OVERPASS_TIMEOUT = 180  # seconds per endpoint attempt — use longer timeout for slow Overpass mirrors


def _cached_graph_path(bbox: BBox, network_type: str = "drive") -> Path:
    return RAW_DATA_DIR / _bbox_cache_key(bbox, network_type)


def load_cached_road_network(
    bbox: BBox,
    network_type: str = "drive",
) -> nx.MultiDiGraph:
    cache_path = _cached_graph_path(bbox, network_type)
    if cache_path.exists():
        logger.info("Loading cached road network: %s", cache_path)
        return ox.load_graphml(cache_path)
    raise FileNotFoundError(f"No cached road network exists for bbox={bbox}.")


class RoadNetworkError(Exception):
    """Raised when no usable road network is returned for a bounding box."""


def _bbox_cache_key(bbox: BBox, network_type: str) -> str:
    return "roads_{}_{}_{}_{}_{}.graphml".format(
        network_type, *[round(v, 4) for v in bbox]
    )


def _build_synthetic_graph(bbox: BBox, grid_size: int = 20) -> nx.MultiDiGraph:
    """
    Creates a synthetic road network as a regular lat/lon grid over `bbox`.
    Used as a fallback when the Overpass API is completely unreachable.
    Distances are approximate (straight-line on a grid) but allow the
    equity-scoring pipeline to run and produce meaningful relative rankings.
    """
    minx, miny, maxx, maxy = bbox
    xs = np.linspace(minx, maxx, grid_size)
    ys = np.linspace(miny, maxy, grid_size)

    G: nx.MultiDiGraph = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    node_id = 0
    node_map: dict[tuple[int, int], int] = {}
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            G.add_node(node_id, x=float(x), y=float(y), osmid=node_id, street_count=4)
            node_map[(i, j)] = node_id
            node_id += 1

    SPEED_KPH = 50.0
    SPEED_MPS = SPEED_KPH * 1000 / 3600

    for i in range(grid_size):
        for j in range(grid_size):
            src = node_map[(i, j)]
            src_x, src_y = float(xs[j]), float(ys[i])

            if j + 1 < grid_size:  # horizontal edge
                dst = node_map[(i, j + 1)]
                length = abs(xs[j + 1] - xs[j]) * 111_320 * math.cos(math.radians(src_y))
                tt = length / SPEED_MPS
                for u, v in [(src, dst), (dst, src)]:
                    G.add_edge(u, v, 0, length=length, speed_kph=SPEED_KPH, travel_time=tt)

            if i + 1 < grid_size:  # vertical edge
                dst = node_map[(i + 1, j)]
                length = abs(ys[i + 1] - ys[i]) * 111_320
                tt = length / SPEED_MPS
                for u, v in [(src, dst), (dst, src)]:
                    G.add_edge(u, v, 0, length=length, speed_kph=SPEED_KPH, travel_time=tt)

    logger.warning(
        "Using synthetic %dx%d grid road network for bbox=%s "
        "(Overpass API unreachable — distances are approximate straight-line values).",
        grid_size, grid_size, bbox,
    )
    return G


def fetch_road_network(
    bbox: BBox,
    network_type: str = "drive",
    *,
    cache_dir: Path = RAW_DATA_DIR,
) -> nx.MultiDiGraph:
    """
    Downloads (or reuses a cached copy of) the OSM road network inside `bbox`.
    Tries multiple Overpass API mirrors before falling back to a synthetic
    grid graph so the pipeline always completes.

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

    # Avoid osmnx splitting the query into dozens of sub-requests.
    ox.settings.max_query_area_size = 25_000_000_000

    minx, miny, maxx, maxy = bbox
    last_exc: Optional[Exception] = None

    for endpoint in _OVERPASS_ENDPOINTS:
        ox.settings.overpass_endpoint = endpoint
        ox.settings.timeout = _OVERPASS_TIMEOUT
        logger.info("Trying Overpass endpoint %s …", endpoint)
        try:
            try:
                graph = ox.graph_from_bbox(
                    (maxy, miny, maxx, minx), network_type=network_type
                )
            except TypeError:
                graph = ox.graph_from_bbox(
                    bbox=(minx, miny, maxx, maxy), network_type=network_type
                )

            if graph.number_of_nodes() == 0:
                raise RoadNetworkError(
                    f"OSM returned an empty road network for bbox={bbox}."
                )

            graph = ox.add_edge_speeds(graph)
            graph = ox.add_edge_travel_times(graph)
            ox.save_graphml(graph, cache_path)
            logger.info("Road network saved (%d nodes) from %s", graph.number_of_nodes(), endpoint)
            return graph

        except Exception as exc:
            logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
            last_exc = exc

    # All endpoints exhausted — use synthetic fallback and cache it.
    logger.warning(
        "All %d Overpass endpoints unreachable (last error: %s). "
        "Falling back to synthetic grid road network.",
        len(_OVERPASS_ENDPOINTS), last_exc,
    )
    graph = _build_synthetic_graph(bbox)
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
