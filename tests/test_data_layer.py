"""
Unit tests for the data_layer modules. All network/file I/O is mocked so
these run fully offline — see the build plan's Section 1.2 requirement.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import Point

from equilibria.data_layer.population import (
    PopulationRaster,
    PopulationDataError,
    population_to_geodataframe,
)
from equilibria.data_layer.facilities import (
    FacilityDataError,
    fetch_existing_facilities,
)


class FakeAffine:
    """Minimal stand-in for rasterio.Affine, just enough for xy() math used in tests."""

    def __init__(self, a, b, c, d, e, f):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f


def test_population_raster_to_geodataframe_basic(monkeypatch):
    import rasterio

    def fake_xy(transform, row, col, offset="center"):
        # simple 1-degree grid starting at (0,0)
        return (col, -row)

    monkeypatch.setattr(rasterio.transform, "xy", fake_xy)

    data = np.array([[10.0, 0.0], [5.0, 20.0]])
    raster = PopulationRaster(data=data, transform=None, crs="EPSG:4326", nodata=0.0, bbox=(0, -2, 2, 0))

    gdf = population_to_geodataframe(raster)
    assert set(gdf.columns) == {"pop_count", "geometry"}
    # the nodata cell (0.0) must be dropped
    assert len(gdf) == 3
    assert gdf["pop_count"].min() > 0


def test_population_raster_raises_when_all_nodata(monkeypatch):
    import rasterio

    monkeypatch.setattr(rasterio.transform, "xy", lambda *a, **k: (0, 0))
    data = np.zeros((2, 2))
    raster = PopulationRaster(data=data, transform=None, crs="EPSG:4326", nodata=0.0, bbox=(0, 0, 1, 1))

    with pytest.raises(PopulationDataError):
        population_to_geodataframe(raster)


def test_fetch_existing_facilities_unknown_source_raises():
    with pytest.raises(FacilityDataError):
        fetch_existing_facilities((0, 0, 1, 1), source="not_a_real_source")


def test_fetch_existing_facilities_nphcda_missing_env_raises(monkeypatch):
    monkeypatch.delenv("NPHCDA_DATA_URL", raising=False)
    with pytest.raises(FacilityDataError):
        fetch_existing_facilities((0, 0, 1, 1), source="nphcda")


def test_fetch_existing_facilities_nphcda_csv(tmp_path):
    csv_path = tmp_path / "facilities.csv"
    csv_path.write_text("name,latitude,longitude,type\nClinic A,12.0,8.5,phc\n")

    gdf = fetch_existing_facilities((8.0, 11.0, 9.0, 13.0), source="nphcda", nphcda_path=str(csv_path))
    assert list(gdf.columns) == ["name", "facility_type", "geometry"]
    assert len(gdf) == 1
    assert gdf.iloc[0]["geometry"] == Point(8.5, 12.0)
