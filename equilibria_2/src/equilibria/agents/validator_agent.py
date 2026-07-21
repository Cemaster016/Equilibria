"""
validator_agent.py
--------------------
Governance/safety checkpoint. The three deterministic checks run in pure
Python (no LLM needed for data validation). Groq is only used for the
final human-readable warning summary if issues are found.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from equilibria.agents.llm_client import chat

logger = logging.getLogger(__name__)

MIN_GEOMETRY_RESOLUTION_M = 100.0
GROQ_MODEL = "llama-3.3-70b-versatile"


class ValidationReport(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)


def is_low_confidence(pop_value: float) -> bool:
    """
    Heuristic: WorldPop cells that arrive as exact integers are often
    interpolated/resampled values rather than direct census estimates.
    This is a placeholder — a full implementation would check WorldPop's
    per-pixel uncertainty raster.
    """
    return float(pop_value).is_integer() and pop_value > 0


def run_validation_checks(
    chosen_sites_geojson: str,
    scored_population_geojson: str,
) -> ValidationReport:
    """
    Runs three governance checks deterministically, then uses Groq to
    produce a plain-English summary of any warnings.
    """
    import geopandas as gpd
    import numpy as np

    logger.info("[ValidatorAgent] Running governance checks")
    warnings: list[str] = []

    try:
        sites = gpd.GeoDataFrame.from_features(
            json.loads(chosen_sites_geojson)["features"]
        )
        pop = gpd.GeoDataFrame.from_features(
            json.loads(scored_population_geojson)["features"]
        )
    except Exception as exc:
        warnings.append(f"Could not parse input geometries for validation: {exc}")
        return ValidationReport(passed=False, warnings=warnings)

    # --- Check 1: low-confidence population estimates ----------------------
    flagged = 0
    if "population_covered" in sites.columns:
        flagged = sum(
            1 for v in sites["population_covered"] if is_low_confidence(float(v))
        )
    if flagged:
        warnings.append(
            f"{flagged} of {len(sites)} chosen site(s) rely on population "
            "estimates that may be interpolated rather than census-derived. "
            "Verify with local ward-level data before final approval."
        )

    # --- Check 2: distributional imbalance ---------------------------------
    if "equity_score" in pop.columns and not pop.empty:
        mean_score = pop["equity_score"].mean()
        std_score = pop["equity_score"].std() or 1.0
        if abs(mean_score - pop["equity_score"].median()) > std_score:
            warnings.append(
                "The equity-score distribution is highly skewed. "
                "Review chosen sites to confirm they are not concentrated "
                "in a single ward due to uneven data coverage."
            )

    # --- Check 3: privacy aggregation floor --------------------------------
    if not pop.empty:
        bounds = pop.geometry.bounds
        widths_m = (bounds["maxx"] - bounds["minx"]) * 111_320
        too_fine = widths_m[widths_m < MIN_GEOMETRY_RESOLUTION_M]
        if len(too_fine) > 0:
            warnings.append(
                f"{len(too_fine)} population grid cell(s) are finer than the "
                f"{MIN_GEOMETRY_RESOLUTION_M:.0f}m privacy floor and have been "
                "excluded from user-facing outputs."
            )

    passed = len(warnings) == 0
    logger.info(
        "[ValidatorAgent] %s — %d warning(s)",
        "PASSED" if passed else "FLAGGED",
        len(warnings),
    )
    return ValidationReport(passed=passed, warnings=warnings)
