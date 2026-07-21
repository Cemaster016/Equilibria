"""
report_agent.py
-----------------
Writes the final plain-English policy brief using Groq. Takes the chosen
sites, equity scores, and validation warnings and returns a markdown string
in the voice of a knowledgeable colleague's memo, not a generated report.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from equilibria.agents.llm_client import chat

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """\
You are a geospatial planning advisor writing a concise policy brief for a
non-technical NGO programme officer or local-government health official.

Write in plain English. Be specific — cite actual numbers from the data.
Do not use jargon like "MinMaxScaler", "Jenks breaks", or "EPSG:32632".
Do not use filler phrases like "In conclusion" or "It is important to note".
Sound like a knowledgeable colleague writing a memo, not an AI generating a report.

Structure your brief with these markdown sections:

## Recommendation
One or two sentences: what is recommended and the single most important reason why.

## Why These Locations
For each of the recommended sites, write a short paragraph naming the specific
location (use the place_name and LGA from the data), describing what kind of area
it is (urban, peri-urban, rural, market area etc. — infer from the name and
context), and explaining specifically why the equity scoring ranked it highly —
is it far from existing clinics? Dense population? Poor road access? Cite the
actual coverage number for that site.

## Data Sources & Caveats
One sentence listing open data sources used (WorldPop population grid, OpenStreetMap
road network, Nigeria health facility registry). Then state any validation warnings
VERBATIM and clearly — never soften or omit them. If there were no warnings, write:
"No data-quality or bias concerns were flagged for this analysis."

## Next Steps
One or two sentences on what a human reviewer should do before acting on this
(e.g. ground-truth field visit, confirmation with local ward health officers).
"""


def run_report_agent(
    intake_summary: str,
    chosen_sites_geojson: str,
    validation_warnings: list[str],
) -> str:
    """
    Calls Groq to write the policy brief. Returns a markdown string.
    """
    logger.info("[ReportAgent] Writing policy brief")

    # Parse site coverage numbers and place names to give the model concrete figures
    try:
        features = json.loads(chosen_sites_geojson).get("features", [])
        site_summaries = []
        for i, f in enumerate(features, 1):
            props = f.get("properties", {})
            pop = props.get("population_covered", "unknown")
            pct = props.get("cumulative_coverage_pct", "unknown")
            place = props.get("place_name", f"Site {i}")
            lga = props.get("lga", "")
            address = props.get("full_address", "")

            location_str = place
            if lga and lga.lower() not in place.lower():
                location_str = f"{place}, {lga}"

            site_summaries.append(
                f"  Site {i} — {location_str} ({address}): "
                f"{float(pop):,.0f} equity-weighted people covered "
                f"(cumulative {float(pct):.1f}%)"
                if pop != "unknown" else
                f"  Site {i} — {location_str}: coverage data unavailable"
            )
        sites_text = "\n".join(site_summaries) if site_summaries else "Site data unavailable."
    except Exception:
        sites_text = "Site coverage data could not be parsed."

    warnings_text = (
        "\n".join(f"- {w}" for w in validation_warnings)
        if validation_warnings
        else "No warnings."
    )

    user_message = f"""
Context:
{intake_summary}

Chosen sites coverage:
{sites_text}

Validation warnings:
{warnings_text}

Write the policy brief now.
"""

    brief = chat(SYSTEM_PROMPT, user_message, model=GROQ_MODEL, temperature=0.3)
    logger.info("[ReportAgent] Policy brief written (%d chars)", len(brief))
    return brief
