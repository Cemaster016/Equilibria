"""
orchestrator.py
-----------------
Drives the full Equilibria pipeline as a simple async Python function.
No ADK session state, no JSON serialisation bugs, no quota black boxes.

Pipeline:
  1. IntakeAgent        — Groq: parse the request
  2. DataFetcherAgent   — deterministic: geocode + download open data
  3. EquityScoringAgent — deterministic: call MCP equity_score tool directly
  4. SiteOptimizerAgent — deterministic: call MCP site_allocate tool directly
  5. ValidatorAgent     — deterministic checks + optional Groq summary
  6. CartographerAgent  — deterministic: call MCP coverage_map tool directly
  7. ReportAgent        — Groq: write the policy brief

Only steps 1, 5 (partially), and 7 touch an LLM. Everything else is
pure spatial Python — fast, deterministic, and quota-free.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from equilibria.agents.intake_agent import run_intake_agent, IntakeResult
from equilibria.agents.validator_agent import run_validation_checks, ValidationReport
from equilibria.agents.report_agent import run_report_agent

logger = logging.getLogger(__name__)


@dataclass
class EquilibriaResult:
    map_html: str = ""
    report_text: str = ""
    validation_warnings: list[str] = field(default_factory=list)
    chosen_sites_geojson: str = ""
    needs_clarification: bool = False
    clarifying_question: str | None = None
    error: str | None = None


async def run_equilibria(user_request: str) -> EquilibriaResult:
    """
    Main entry point for the Streamlit UI.
    Runs the full pipeline and returns an EquilibriaResult.
    All errors are caught and surfaced cleanly — never crashes the UI.
    """
    try:
        return await _pipeline(user_request)
    except Exception as exc:
        logger.exception("Equilibria pipeline failed")
        return EquilibriaResult(error=f"{type(exc).__name__}: {exc}")


async def _pipeline(user_request: str) -> EquilibriaResult:

    # ------------------------------------------------------------------
    # Step 1 — Intake (Groq)
    # ------------------------------------------------------------------
    logger.info("Step 1/7: IntakeAgent — parsing request")
    intake: IntakeResult = run_intake_agent(user_request)

    if intake.needs_clarification:
        return EquilibriaResult(
            needs_clarification=True,
            clarifying_question=intake.clarifying_question,
        )

    # ------------------------------------------------------------------
    # Step 2 — Data fetching (deterministic)
    # ------------------------------------------------------------------
    logger.info("Step 2/7: DataFetcherAgent — fetching open data for %s",
                intake.location_name)
    from equilibria.agents.data_fetcher_agent import fetch_area_data

    fetched = fetch_area_data(intake.location_name)
    if fetched.get("error"):
        return EquilibriaResult(
            error=f"Data fetching failed: {fetched['error']}"
        )

    pop_path       = fetched["population_geojson_path"]
    road_path      = fetched["road_graph_path"]
    facilities_path = fetched["facilities_geojson_path"]

    for label, path in [
        ("population", pop_path),
        ("road network", road_path),
        ("facilities", facilities_path),
    ]:
        if not path or not Path(path).exists():
            return EquilibriaResult(
                error=f"DataFetcherAgent did not produce a {label} file."
            )

    # ------------------------------------------------------------------
    # Step 3 — Equity scoring (deterministic, calls spatial_tools directly)
    # ------------------------------------------------------------------
    logger.info("Step 3/7: EquityScoringAgent — scoring population grid")
    scored_population_geojson = _equity_score(
        pop_path, facilities_path, road_path, intake
    )

    # ------------------------------------------------------------------
    # Step 4 — Site optimisation (deterministic, calls spatial_tools directly)
    # ------------------------------------------------------------------
    logger.info("Step 4/7: SiteOptimizerAgent — choosing %d sites", intake.num_sites)
    chosen_sites_geojson, error = _site_allocate(
        road_path, scored_population_geojson, intake
    )
    if error:
        return EquilibriaResult(error=error)

    # ------------------------------------------------------------------
    # Step 5 — Validation (deterministic checks)
    # ------------------------------------------------------------------
    logger.info("Step 5/7: ValidatorAgent — running governance checks")
    validation: ValidationReport = run_validation_checks(
        chosen_sites_geojson, scored_population_geojson
    )

    # ------------------------------------------------------------------
    # Step 6 — Map rendering (deterministic)
    # ------------------------------------------------------------------
    logger.info("Step 6/7: CartographerAgent — rendering map")
    map_html = _render_map(chosen_sites_geojson, scored_population_geojson, facilities_path)

    # ------------------------------------------------------------------
    # Step 7 — Report (Groq)
    # ------------------------------------------------------------------
    logger.info("Step 7/7: ReportAgent — writing policy brief")
    intake_summary = (
        f"Location: {intake.location_name}\n"
        f"Number of new sites requested: {intake.num_sites}\n"
        f"Target population: {intake.target_population}\n"
        f"Budget per site: {intake.budget_per_site or 'not specified'}\n"
        f"Total budget: {intake.total_budget or 'not specified'}"
    )
    report_text = run_report_agent(
        intake_summary, chosen_sites_geojson, validation.warnings
    )

    logger.info("Pipeline complete.")
    return EquilibriaResult(
        map_html=map_html,
        report_text=report_text,
        validation_warnings=validation.warnings,
        chosen_sites_geojson=chosen_sites_geojson,
    )


# ------------------------------------------------------------------
# Private helpers — call spatial_tools functions directly
# ------------------------------------------------------------------

def _equity_score(
    pop_path: str,
    facilities_path: str,
    road_path: str,
    intake: IntakeResult,
) -> str:
    import geopandas as gpd
    import osmnx as ox
    from equilibria.mcp_server.spatial_tools import equity_score

    pop_gdf = gpd.read_file(pop_path)
    facilities_gdf = gpd.read_file(facilities_path)
    road_graph = ox.load_graphml(road_path)

    weights = {
        "density":     intake.equity_weight_hints.density,
        "distance":    intake.equity_weight_hints.distance,
        "road_access": intake.equity_weight_hints.road_access,
    }
    scored = equity_score(pop_gdf, facilities_gdf, road_graph, weights=weights)
    return scored.to_json()


def _site_allocate(
    road_path: str,
    scored_population_geojson: str,
    intake: IntakeResult,
    service_radius_m: float = 5000.0,
) -> tuple[str, str | None]:
    import geopandas as gpd
    import osmnx as ox
    from equilibria.mcp_server.spatial_tools import (
        candidate_sites_from_road_graph,
        site_allocate,
        SpatialToolError,
    )

    road_graph = ox.load_graphml(road_path)
    candidates = candidate_sites_from_road_graph(road_graph, max_candidates=300)
    scored_gdf = gpd.GeoDataFrame.from_features(
        json.loads(scored_population_geojson)["features"], crs="EPSG:4326"
    )

    try:
        chosen = site_allocate(
            candidates,
            scored_gdf,
            k=intake.num_sites,
            budget_per_site=intake.budget_per_site,
            total_budget=intake.total_budget,
            service_radius_m=service_radius_m,
        )
        return chosen.to_json(), None
    except SpatialToolError as exc:
        # One automatic retry with a larger service radius
        logger.warning("site_allocate failed (%s) — retrying with 10km radius", exc)
        try:
            chosen = site_allocate(
                candidates, scored_gdf,
                k=intake.num_sites, service_radius_m=service_radius_m * 2,
            )
            return chosen.to_json(), None
        except SpatialToolError as exc2:
            return "", f"Site optimisation failed: {exc2}"


def _render_map(
    chosen_sites_geojson: str,
    scored_population_geojson: str,
    facilities_path: str,
) -> str:
    import geopandas as gpd
    from equilibria.mcp_server.spatial_tools import coverage_map

    chosen_gdf = gpd.GeoDataFrame.from_features(
        json.loads(chosen_sites_geojson)["features"], crs="EPSG:4326"
    )
    scored_gdf = gpd.GeoDataFrame.from_features(
        json.loads(scored_population_geojson)["features"], crs="EPSG:4326"
    )
    facilities_gdf = gpd.read_file(facilities_path)

    folium_map = coverage_map(chosen_gdf, scored_gdf, facilities_gdf)
    return folium_map._repr_html_()
