"""
Unit tests for the MCP server's underlying pure functions in spatial_tools.py.
Uses a tiny synthetic fixture (no real network/road data) so these run fast
and fully offline, matching the build plan's integration-test approach.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import Point, box

from equilibria.mcp_server.spatial_tools import (
    equity_score,
    site_allocate,
    candidate_sites_from_road_graph,
    SpatialToolError,
    _validate_weights,
)


def _toy_population_gdf() -> gpd.GeoDataFrame:
    # a simple 2x2 grid of 1km cells with very different population counts
    cells = [
        (box(0, 0, 0.01, 0.01), 1000),   # dense, near nothing
        (box(0.01, 0, 0.02, 0.01), 10),  # sparse
        (box(0, 0.01, 0.01, 0.02), 500),
        (box(0.01, 0.01, 0.02, 0.02), 5),
    ]
    return gpd.GeoDataFrame(
        {"geometry": [c[0] for c in cells], "pop_count": [c[1] for c in cells]},
        crs="EPSG:4326",
    )


def _toy_facilities_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"geometry": [Point(0.015, 0.005)], "name": ["Existing Clinic"], "facility_type": ["clinic"]},
        crs="EPSG:4326",
    )


def _toy_road_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    # four nodes roughly matching the corners of the toy population grid
    coords = {0: (0.0, 0.0), 1: (0.02, 0.0), 2: (0.0, 0.02), 3: (0.02, 0.02)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    g.add_edge(0, 1, length=2000, travel_time=120)
    g.add_edge(1, 0, length=2000, travel_time=120)
    g.add_edge(0, 2, length=2000, travel_time=120)
    g.add_edge(2, 0, length=2000, travel_time=120)
    g.add_edge(1, 3, length=2000, travel_time=120)
    g.add_edge(3, 1, length=2000, travel_time=120)
    g.add_edge(2, 3, length=2000, travel_time=120)
    g.add_edge(3, 2, length=2000, travel_time=120)
    return g


def test_validate_weights_rejects_bad_sum():
    with pytest.raises(SpatialToolError):
        _validate_weights({"density": 0.5, "distance": 0.5, "road_access": 0.5})


def test_validate_weights_rejects_missing_key():
    with pytest.raises(SpatialToolError):
        _validate_weights({"density": 1.0})


def test_equity_score_adds_expected_columns():
    pop = _toy_population_gdf()
    facilities = _toy_facilities_gdf()
    graph = _toy_road_graph()

    scored = equity_score(pop, facilities, graph)
    assert "equity_score" in scored.columns
    assert scored["equity_score"].between(0, 100).all()
    # the densest, most-isolated cell should score higher than the sparsest one
    assert scored.iloc[0]["equity_score"] > scored.iloc[3]["equity_score"]


def test_equity_score_rejects_empty_inputs():
    empty = gpd.GeoDataFrame(columns=["pop_count", "geometry"], geometry="geometry", crs="EPSG:4326")
    facilities = _toy_facilities_gdf()
    graph = _toy_road_graph()
    with pytest.raises(SpatialToolError):
        equity_score(empty, facilities, graph)


def test_site_allocate_picks_requested_k():
    pop = _toy_population_gdf()
    facilities = _toy_facilities_gdf()
    graph = _toy_road_graph()
    scored = equity_score(pop, facilities, graph)

    candidates = candidate_sites_from_road_graph(graph, max_candidates=10)
    chosen = site_allocate(candidates, scored, k=2, service_radius_m=3000)

    assert len(chosen) <= 2
    assert "population_covered" in chosen.columns
    assert "cumulative_coverage_pct" in chosen.columns
    # coverage should be non-decreasing as more sites are added
    assert list(chosen["cumulative_coverage_pct"]) == sorted(chosen["cumulative_coverage_pct"])


def test_site_allocate_raises_with_no_candidates():
    pop = _toy_population_gdf()
    facilities = _toy_facilities_gdf()
    graph = _toy_road_graph()
    scored = equity_score(pop, facilities, graph)

    empty_candidates = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    with pytest.raises(SpatialToolError):
        site_allocate(empty_candidates, scored, k=2)


def test_candidate_sites_from_road_graph_returns_points():
    graph = _toy_road_graph()
    candidates = candidate_sites_from_road_graph(graph)
    assert len(candidates) > 0
    assert all(geom.geom_type == "Point" for geom in candidates.geometry)
