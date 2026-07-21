"""
population.py
--------------
Fetches WorldPop population-count rasters and converts them into a
GeoDataFrame of grid-cell points carrying a `pop_count` column, which is
the format every downstream Equilibria tool (equity_score, site_allocate)
expects.

WorldPop publishes free, open 100m-resolution gridded population estimates
at https://hub.worldpop.org. This module downloads the constrained,
UN-adjusted national total raster for a given country and clips it to a
bounding box, caching the result locally so repeated runs (and live demos)
don't re-download.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import box

logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(os.getenv("EQUILIBRIA_RAW_DATA_DIR", "data/raw")) / "population"

# WorldPop's "constrained, UN-adjusted" 2020 100m population-count GeoTIFFs.
# Verified against https://hub.worldpop.org/geodata/summary?id=49705 (Nigeria):
# real download URL uses the "maxar_v1" path segment, not "BSGM" as some older
# mirrors/docs suggest. No API key or auth required — these are open downloads.
WORLDPOP_URL_TEMPLATE = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/"
    "2020/maxar_v1/{iso3_upper}/{iso3_lower}_ppp_2020_UNadj_constrained.tif"
)

BBox = tuple[float, float, float, float]  # (minx, miny, maxx, maxy) in lon/lat


class PopulationDataError(Exception):
    """Raised when population data cannot be fetched or contains no usable cells."""


def _default_downloader(url: str, dest_path: Path) -> Path:
    """Streams a URL to disk. Kept separate from fetch_population_grid so tests
    can inject a fake downloader instead of hitting the network."""
    import requests  # local import: keeps this an optional runtime dependency

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    return dest_path


def fetch_population_grid(
    bbox: BBox,
    country_iso3: str = "NGA",
    *,
    _downloader: Callable[[str, Path], Path] = _default_downloader,
    cache_dir: Path = RAW_DATA_DIR,
) -> "PopulationRaster":
    """
    Downloads (or reuses a cached copy of) the WorldPop raster for `country_iso3`,
    clips it to `bbox`, and returns a PopulationRaster wrapper.

    Parameters
    ----------
    bbox : (minx, miny, maxx, maxy) in EPSG:4326 (lon/lat degrees)
    country_iso3 : ISO3166-1 alpha-3 country code, e.g. "NGA" for Nigeria
    _downloader : injectable for testing — defaults to a real HTTP streaming download
    cache_dir : where the full-country raster is cached between runs

    Raises
    ------
    PopulationDataError if the bbox yields zero valid population cells.
    """
    import rasterio
    from rasterio.windows import from_bounds

    iso3_lower = country_iso3.lower()
    cache_path = cache_dir / f"{iso3_lower}_ppp_2020_UNadj_constrained.tif"

    if not cache_path.exists():
        url = WORLDPOP_URL_TEMPLATE.format(iso3_lower=iso3_lower, iso3_upper=country_iso3.upper())
        logger.info("Downloading WorldPop raster for %s -> %s", country_iso3, cache_path)
        _downloader(url, cache_path)
    else:
        logger.info("Using cached WorldPop raster: %s", cache_path)

    with rasterio.open(cache_path) as src:
        window = from_bounds(*bbox, transform=src.transform)
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        nodata = src.nodata
        crs = src.crs

    if data.size == 0 or (nodata is not None and np.all(data == nodata)):
        raise PopulationDataError(
            f"No population data found for bbox={bbox} in country={country_iso3}. "
            "Check that the bounding box actually falls inside that country."
        )

    return PopulationRaster(data=data, transform=transform, crs=crs, nodata=nodata, bbox=bbox)


@dataclass
class PopulationRaster:
    """Thin wrapper around a clipped population raster plus its georeferencing info."""

    data: np.ndarray
    transform: "rasterio.Affine"
    crs: object
    nodata: Optional[float]
    bbox: BBox

    def to_geodataframe(self, min_pop_threshold: float = 0.0) -> gpd.GeoDataFrame:
        """
        Converts every valid raster cell into a square polygon feature with a
        `pop_count` column. Cells below `min_pop_threshold` (or equal to nodata)
        are dropped to keep the output lightweight for downstream agents.
        """
        import rasterio

        rows, cols = self.data.shape
        records = []
        for r in range(rows):
            for c in range(cols):
                value = float(self.data[r, c])
                if self.nodata is not None and value == self.nodata:
                    continue
                if value <= min_pop_threshold:
                    continue
                minx, maxy = rasterio.transform.xy(self.transform, r, c, offset="ul")
                maxx, miny = rasterio.transform.xy(self.transform, r, c, offset="lr")
                records.append(
                    {"pop_count": value, "geometry": box(minx, miny, maxx, maxy)}
                )

        if not records:
            raise PopulationDataError(
                "Population raster clipped to zero usable cells after thresholding."
            )

        gdf = gpd.GeoDataFrame(records, crs=self.crs)
        return gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf


def population_to_geodataframe(raster: PopulationRaster, **kwargs) -> gpd.GeoDataFrame:
    """Convenience wrapper — see PopulationRaster.to_geodataframe."""
    return raster.to_geodataframe(**kwargs)
