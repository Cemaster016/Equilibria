"""
facilities.py
--------------
Loads "existing facility" point data — either from OpenStreetMap (free,
global, works anywhere) or from a downloaded registry file such as the
HDX Nigeria hospitals/clinics dataset (.xlsx, .csv, .shp, .geojson).

Both sources are normalized into the same schema:
    columns: ['name', 'facility_type', 'geometry']
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

BBox = tuple[float, float, float, float]  # (minx, miny, maxx, maxy) in lon/lat

NORMALIZED_COLUMNS = ["name", "facility_type", "geometry"]


class FacilityDataError(Exception):
    """Raised when no facilities are found, or a source is misconfigured."""


def fetch_existing_facilities(
    bbox: BBox,
    source: str = "osm",
    *,
    nphcda_path: Optional[str] = None,
) -> gpd.GeoDataFrame:
    if source == "osm":
        gdf = _fetch_from_osm(bbox)
    elif source == "nphcda":
        path = nphcda_path or os.getenv("NPHCDA_DATA_URL")
        if not path:
            raise FacilityDataError(
                "source='nphcda' requires nphcda_path or the NPHCDA_DATA_URL "
                "environment variable to be set to a local file path."
            )
        gdf = _fetch_from_file(path.strip(), bbox)
    else:
        raise FacilityDataError(
            f"Unknown facility source '{source}'. Use 'osm' or 'nphcda'."
        )

    if gdf.empty:
        raise FacilityDataError(
            f"No existing facilities found for bbox={bbox} via source='{source}'."
        )

    return gdf[NORMALIZED_COLUMNS]


def _fetch_from_osm(bbox: BBox) -> gpd.GeoDataFrame:
    import osmnx as ox

    minx, miny, maxx, maxy = bbox
    tags = {"amenity": ["clinic", "hospital", "doctors", "health_post"]}
    try:
        gdf = ox.features.features_from_bbox((maxy, miny, maxx, minx), tags=tags)
    except TypeError:
        gdf = ox.features.features_from_bbox(bbox=(minx, miny, maxx, maxy), tags=tags)

    if gdf.empty:
        return gpd.GeoDataFrame(
            columns=NORMALIZED_COLUMNS, geometry="geometry", crs="EPSG:4326"
        )

    gdf = gdf.reset_index()
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g if g.geom_type == "Point" else g.representative_point()
    )
    gdf["name"] = gdf.get("name", pd.Series(dtype=str)).fillna("Unnamed facility")
    gdf["facility_type"] = gdf.get("amenity", pd.Series(dtype=str)).fillna("unknown")
    return gdf[NORMALIZED_COLUMNS].set_geometry("geometry", crs="EPSG:4326")


def _fetch_from_file(path: str, bbox: BBox) -> gpd.GeoDataFrame:
    p = Path(path)
    if not p.exists():
        raise FacilityDataError(
            f"Facility file not found: {path}\n"
            "Check that NPHCDA_DATA_URL in your .env has no leading/trailing spaces."
        )

    suffix = p.suffix.lower()

    if suffix in (".shp", ".geojson", ".gpkg"):
        return _load_vector_file(p, bbox)

    if suffix == ".csv":
        df = pd.read_csv(p)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(p, engine="openpyxl")
    else:
        raise FacilityDataError(
            f"Unsupported file type '{suffix}'. "
            "Supported: .xlsx, .xls, .csv, .shp, .geojson, .gpkg"
        )

    df = _strip_hxl_row(df)

    lat_col = _find_column(df, ("lat", "latitude", "y", "geo_lat"))
    lon_col = _find_column(df, ("lon", "lng", "longitude", "x", "geo_lon"))

    if not lat_col or not lon_col:
        raise FacilityDataError(
            f"Could not detect latitude/longitude columns in {p.name}.\n"
            f"Columns found: {list(df.columns)}\n"
            "Rename your lat/lon columns to 'latitude'/'longitude' and try again."
        )

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)

    if df.empty:
        raise FacilityDataError(
            f"{p.name} had no rows with valid numeric coordinates after cleaning."
        )

    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )

    minx, miny, maxx, maxy = bbox
    gdf = gdf.cx[minx:maxx, miny:maxy].copy()

    if gdf.empty:
        raise FacilityDataError(
            f"{p.name} loaded ({len(df)} total rows) but no facilities "
            f"fall inside bbox={bbox}."
        )

    logger.info("Loaded %d facilities from %s", len(gdf), p.name)

    name_col = _find_column(
        gdf, ("name", "facility_name", "facility name", "fname")
    )
    type_col = _find_column(
        gdf, ("type", "facility_type", "facility type", "category")
    )
    gdf["name"] = (
        gdf[name_col].fillna("Unnamed facility") if name_col else "Unnamed facility"
    )
    gdf["facility_type"] = (
        gdf[type_col].fillna("primary_healthcare") if type_col else "primary_healthcare"
    )
    return gdf


def _load_vector_file(p: Path, bbox: BBox) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(p)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    minx, miny, maxx, maxy = bbox
    gdf = gdf.cx[minx:maxx, miny:maxy].copy()
    name_col = _find_column(gdf, ("name", "facility_name"))
    type_col = _find_column(gdf, ("type", "facility_type", "category"))
    gdf["name"] = gdf[name_col] if name_col else "Unnamed facility"
    gdf["facility_type"] = gdf[type_col] if type_col else "primary_healthcare"
    return gdf


def _strip_hxl_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    HDX exports include a HXL hashtag row directly under the column headers,
    e.g. '#geo +lat', '#loc +name'. Detects and removes it so it does not
    get parsed as a fake facility with garbage coordinates.
    """
    if df.empty:
        return df
    first_row = df.iloc[0]
    hxl_count = sum(
        1 for v in first_row
        if isinstance(v, str) and v.strip().startswith("#")
    )
    if hxl_count >= max(1, len(df.columns) // 2):
        logger.info("HXL hashtag header row detected and removed.")
        return df.iloc[1:].reset_index(drop=True)
    return df


def _find_column(df, candidates: tuple) -> Optional[str]:
    """Case-insensitive column name lookup against a list of known candidates."""
    lowered = {c.lower().strip(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None