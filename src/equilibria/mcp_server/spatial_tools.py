"""
spatial_tools.py
-----------------
The actual analytical core of Equilibria. Three pure, fully-testable
functions — these get wrapped as MCP tools in server.py, but they contain
zero MCP-specific code so they can be unit tested and reused directly.

1. equity_score   — Week 5 (clustering/hotspot) skillset: scores every
                     population cell on how underserved it is.
2. site_allocate   — classic location-allocation (greedy maximum coverage),
                     using the equity scores + Week 7 network-distance logic.
3. coverage_map    — Week 4 (thematic mapping) skillset: renders the result.
"""

from __future__ import annotations

import logging
from typing import Optional

import geopandas as gpd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from shapely.geometry import Point

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {"density": 0.4, "distance": 0.4, "road_access": 0.2}


class SpatialToolError(Exception):
    """Raised on invalid inputs to any of the spatial tools below."""


# ---------------------------------------------------------------------------
# 1. equity_score
# ---------------------------------------------------------------------------
def equity_score(
    pop_gdf: gpd.GeoDataFrame,
    facilities_gdf: gpd.GeoDataFrame,
    road_graph,
    weights: Optional[dict] = None,
    *,
    max_facilities_for_distance: int = 500,
) -> gpd.GeoDataFrame:
    """
    Adds an `equity_score` column (0-100, higher = more underserved/higher
    priority) to a copy of `pop_gdf`, computed as a weighted blend of:

        - density_score      : normalized population count (denser = higher priority)
        - distance_score      : normalized network distance to nearest existing
                                  facility (farther = higher priority)
        - road_access_score   : 1.0 if the cell centroid is farther than 1km
                                  (straight-line, as a fast proxy) from any mapped
                                  road, else 0.0 — flags road-access poverty

    Parameters
    ----------
    pop_gdf : GeoDataFrame with a 'pop_count' column (from data_layer.population)
    facilities_gdf : GeoDataFrame of existing facilities (from data_layer.facilities)
    road_graph : networkx graph from data_layer.roads.fetch_road_network
    weights : dict with keys 'density', 'distance', 'road_access' summing to 1.0.
              Defaults to DEFAULT_WEIGHTS if not supplied.
    max_facilities_for_distance : caps how many facilities are considered per
              cell when computing nearest-facility network distance, to keep
              runtime bounded on large facility lists (uses the nearest-by-
              straight-line subset first, which is a safe approximation).

    Raises
    ------
    SpatialToolError if weights don't sum to 1.0, or if either input
    GeoDataFrame is empty.
    """
    from equilibria.data_layer.roads import nearest_facility_distance

    weights = weights or DEFAULT_WEIGHTS
    _validate_weights(weights)

    if pop_gdf.empty:
        raise SpatialToolError("equity_score received an empty population GeoDataFrame.")
    if facilities_gdf.empty:
        raise SpatialToolError("equity_score received an empty facilities GeoDataFrame.")

    gdf = pop_gdf.copy()
    # Project to a metric CRS before computing centroids/distances — UTM 32N
    # covers Nigeria adequately for the capstone demo; a general deployment
    # would pick this dynamically from the bbox (see site_allocate's TODO-style
    # note on the same limitation).
    gdf_m = gdf.to_crs(epsg=32632)
    centroids_m = gdf_m.geometry.centroid
    centroids = gpd.GeoSeries(centroids_m, crs=32632).to_crs(epsg=4326)

    # --- density score -----------------------------------------------------
    gdf["density_score"] = _minmax(gdf["pop_count"].to_numpy())

    # --- distance score: vectorized Euclidean (fast proxy for equity scoring) ---
    # Exact network routing is not needed for relative distance ranking.
    # Euclidean reduces runtime from 30 min to <30 seconds for 44k cells.
    from scipy.spatial import cKDTree

    pop_m = gdf.to_crs(epsg=32632)
    fac_m = facilities_gdf.to_crs(epsg=32632)

    pop_xy = np.column_stack([
        pop_m.geometry.centroid.x.to_numpy(),
        pop_m.geometry.centroid.y.to_numpy()
    ])
    fac_xy = np.column_stack([
        fac_m.geometry.centroid.x.to_numpy(),
        fac_m.geometry.centroid.y.to_numpy()
    ])

    # For each population cell, find Euclidean distance to nearest facility
    tree = cKDTree(fac_xy)
    distances, _ = tree.query(pop_xy, k=1)
    gdf["distance_score"] = _minmax(distances)

    # --- road access score ---------------------------------------------------
    gdf["road_access_score"] = _road_access_proxy(centroids, road_graph)

    gdf["equity_score"] = 100 * (
        weights["density"] * gdf["density_score"]
        + weights["distance"] * gdf["distance_score"]
        + weights["road_access"] * gdf["road_access_score"]
    )
    return gdf


def _validate_weights(weights: dict) -> None:
    required = {"density", "distance", "road_access"}
    if set(weights.keys()) != required:
        raise SpatialToolError(f"weights must have exactly these keys: {required}")
    total = sum(weights.values())
    if not np.isclose(total, 1.0, atol=1e-6):
        raise SpatialToolError(f"weights must sum to 1.0, got {total}")


def _minmax(arr: np.ndarray) -> np.ndarray:
    if np.allclose(arr.max(), arr.min()):
        return np.zeros_like(arr, dtype=float)
    scaled = MinMaxScaler().fit_transform(arr.reshape(-1, 1)).ravel()
    return scaled


def _road_access_proxy(centroids, road_graph, threshold_m: float = 1000.0) -> np.ndarray:
    """Fast straight-line proxy for 'is this cell far from any mapped road'.
    Uses node coordinates already in the graph rather than re-querying OSM."""
    import osmnx as ox

    if road_graph.number_of_nodes() == 0:
        return np.ones(len(centroids))

    node_xy = np.array([[data["x"], data["y"]] for _, data in road_graph.nodes(data=True)])
    scores = []
    for pt in centroids:
        d_deg = np.min(np.sqrt((node_xy[:, 0] - pt.x) ** 2 + (node_xy[:, 1] - pt.y) ** 2))
        d_m = d_deg * 111_320  # rough degrees->metres at the equator; fine for a proxy
        scores.append(1.0 if d_m > threshold_m else 0.0)
    return np.array(scores)


# ---------------------------------------------------------------------------
# 2. site_allocate
# ---------------------------------------------------------------------------
def site_allocate(
    candidate_points_gdf: gpd.GeoDataFrame,
    pop_gdf: gpd.GeoDataFrame,
    k: int,
    *,
    budget_per_site: Optional[float] = None,
    total_budget: Optional[float] = None,
    service_radius_m: float = 5000.0,
) -> gpd.GeoDataFrame:
    """
    Greedy maximum-coverage location-allocation: iteratively picks the
    candidate site that covers the most still-uncovered equity_score-weighted
    population within `service_radius_m`, removes that covered population
    from contention, and repeats until `k` sites are chosen (or the budget
    runs out, whichever comes first).

    NOTE ON ALGORITHM CHOICE: the exact maximal covering location problem is
    NP-hard. This greedy heuristic is a well-established 1 - 1/e
    approximation-guaranteed strategy (Cornuejols, Fisher & Nemhauser, 1977)
    that runs in seconds rather than minutes — the right tradeoff for an
    agent that needs to respond conversationally, not for a one-off
    overnight optimization batch job.

    Parameters
    ----------
    candidate_points_gdf : GeoDataFrame of possible new-site locations
    pop_gdf : output of equity_score() — must contain 'equity_score' and 'pop_count'
    k : number of sites to choose
    budget_per_site, total_budget : if both given, k is capped at
        floor(total_budget / budget_per_site) regardless of the requested k
    service_radius_m : how far a site is assumed to "cover" surrounding population

    Returns
    -------
    GeoDataFrame of the chosen sites with columns:
        'population_covered', 'cumulative_coverage_pct'
    """
    if candidate_points_gdf.empty:
        raise SpatialToolError("site_allocate received no candidate sites.")
    if "equity_score" not in pop_gdf.columns:
        raise SpatialToolError("pop_gdf must already have an 'equity_score' column — run equity_score() first.")

    if budget_per_site and total_budget:
        affordable_k = int(total_budget // budget_per_site)
        k = min(k, affordable_k)
        if k <= 0:
            raise SpatialToolError("total_budget is too small to afford even one site at budget_per_site.")

    # Project to metres for accurate radius math (UTM 32N covers most of Nigeria;
    # for a general deployment this should be picked dynamically from the bbox).
    pop_m = pop_gdf.to_crs(epsg=32632)
    cand_m = candidate_points_gdf.to_crs(epsg=32632)

    weighted_pop = pop_m["pop_count"].to_numpy() * (pop_m["equity_score"].to_numpy() / 100.0)
    pop_centroids = pop_m.geometry.centroid
    pop_xy = np.column_stack([pop_centroids.x.to_numpy(), pop_centroids.y.to_numpy()])

    remaining = weighted_pop.copy()
    total_weighted_pop = weighted_pop.sum()
    if total_weighted_pop <= 0:
        raise SpatialToolError("Total equity-weighted population is zero — check inputs.")

    chosen_idx: list[int] = []
    chosen_coverage: list[float] = []
    cumulative = 0.0

    cand_xy = np.column_stack([cand_m.geometry.x.to_numpy(), cand_m.geometry.y.to_numpy()])
    available = list(range(len(cand_m)))

    for _ in range(k):
        if not available or remaining.sum() <= 0:
            break
        best_idx, best_gain, best_mask = None, -1.0, None
        for ci in available:
            dists = np.sqrt(((pop_xy - cand_xy[ci]) ** 2).sum(axis=1))
            mask = dists <= service_radius_m
            gain = remaining[mask].sum()
            if gain > best_gain:
                best_idx, best_gain, best_mask = ci, gain, mask
        if best_idx is None or best_gain <= 0:
            break
        chosen_idx.append(best_idx)
        chosen_coverage.append(best_gain)
        cumulative += best_gain
        remaining[best_mask] = 0.0
        available.remove(best_idx)

    if not chosen_idx:
        raise SpatialToolError("No candidate site covers any population within service_radius_m.")

    result = candidate_points_gdf.iloc[chosen_idx].copy()
    result["population_covered"] = chosen_coverage
    result["cumulative_coverage_pct"] = (
        np.cumsum(chosen_coverage) / total_weighted_pop * 100
    )
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. coverage_map
# ---------------------------------------------------------------------------
def coverage_map(
    chosen_sites_gdf: gpd.GeoDataFrame,
    pop_gdf: gpd.GeoDataFrame,
    existing_facilities_gdf: gpd.GeoDataFrame,
):
    """
    Builds a lightweight interactive folium map using HeatMap for population
    equity scores (instead of 44k individual polygons) to stay within 1GB RAM.
    """
    import folium
    from folium.plugins import HeatMap

    if pop_gdf.empty:
        raise SpatialToolError("coverage_map received an empty population GeoDataFrame.")

    # Use centroids for heatmap — project to metric CRS first to fix CRS warning
    pop_m = pop_gdf.to_crs(epsg=32632)
    centroids = pop_m.geometry.centroid.to_crs(epsg=4326)
    center = [centroids.y.mean(), centroids.x.mean()]

    m = folium.Map(location=center, zoom_start=11, tiles="cartodbpositron")

    # --- equity score heatmap (replaces 44k polygon GeoJson objects) ----------
    # Sample max 3000 points to keep HTML under 5MB
    sample_gdf = pop_gdf.copy()
    sample_gdf["centroid_lat"] = centroids.y.values
    sample_gdf["centroid_lon"] = centroids.x.values

    if len(sample_gdf) > 3000:
        sample_gdf = sample_gdf.nlargest(3000, "equity_score")

    heat_data = [
        [row["centroid_lat"], row["centroid_lon"], row["equity_score"] / 100]
        for _, row in sample_gdf.iterrows()
    ]
    HeatMap(
        heat_data,
        min_opacity=0.3,
        radius=18,
        blur=15,
        gradient={0.2: "#fee5d9", 0.5: "#fb6a4a", 0.8: "#de2d26", 1.0: "#a50f15"},
    ).add_to(m)

    # --- existing facilities (grey dots) -------------------------------------
    for _, row in existing_facilities_gdf.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            color="#555555",
            fill=True,
            fill_opacity=0.8,
            popup=f"Existing: {row.get('name', 'facility')}",
        ).add_to(m)

    # --- proposed sites (green stars) ----------------------------------------
    for _, row in chosen_sites_gdf.iterrows():
        pop_covered = row.get("population_covered", 0)
        cum_pct = row.get("cumulative_coverage_pct", 0)
        place = row.get("place_name", "Proposed site")
        popup_html = (
            f"<b>{place}</b><br>"
            f"Population covered: {float(pop_covered):,.0f}<br>"
            f"Cumulative coverage: {float(cum_pct):.1f}%"
        )
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            icon=folium.Icon(color="green", icon="star"),
            popup=folium.Popup(popup_html, max_width=250),
        ).add_to(m)

    return m

def _jenks_breaks(values: np.ndarray, n_classes: int = 5) -> list[float]:
    """Lightweight natural-breaks approximation using quantiles when the
    jenkspy package isn't available, so this tool has no hard dependency
    beyond what's already in pyproject.toml."""
    try:
        import jenkspy

        return jenkspy.jenks_breaks(values, n_classes=n_classes)
    except ImportError:
        quantiles = np.linspace(0, 100, n_classes + 1)
        return list(np.percentile(values, quantiles))


def _classify(value: float, breaks: list[float]) -> int:
    for i in range(len(breaks) - 1):
        if value <= breaks[i + 1]:
            return min(i, len(breaks) - 2)
    return len(breaks) - 2


# ---------------------------------------------------------------------------
# Helper: candidate site generation from a road network
# ---------------------------------------------------------------------------
def candidate_sites_from_road_graph(road_graph, max_candidates: int = 300) -> gpd.GeoDataFrame:
    """
    Generates a GeoDataFrame of plausible new-facility candidate locations
    from a road network's intersection nodes — a reasonable real-world proxy,
    since facilities need road access to be useful/reachable, and intersections
    are typically where existing settlements/services already cluster.

    If the graph has more nodes than `max_candidates`, evenly subsamples to
    keep site_allocate's runtime bounded.
    """
    from shapely.geometry import Point

    nodes = [
        (data["x"], data["y"])
        for _, data in road_graph.nodes(data=True)
        if road_graph.degree(_) >= 3  # intersections only, not mid-road points
    ]
    if not nodes:
        # fall back to all nodes if nothing qualifies as a true intersection
        nodes = [(data["x"], data["y"]) for _, data in road_graph.nodes(data=True)]

    if len(nodes) > max_candidates:
        step = max(1, len(nodes) // max_candidates)
        nodes = nodes[::step]

    if not nodes:
        raise SpatialToolError("Road graph contains no usable nodes for candidate site generation.")

    return gpd.GeoDataFrame(
        {"geometry": [Point(x, y) for x, y in nodes]},
        crs="EPSG:4326",
    )
