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
Explain the equity logic in everyday language. Cite the actual coverage numbers
(population_covered, cumulative_coverage_pct). Explain what "equity-weighted" means
in terms the reader understands: these locations were prioritised because they are
the farthest from existing clinics, have the highest population density, and/or
have the poorest road access — not because they generate the most revenue.

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

    # Parse site coverage numbers to give the model concrete figures
    try:
        features = json.loads(chosen_sites_geojson).get("features", [])
        site_summaries = []
        for i, f in enumerate(features, 1):
            props = f.get("properties", {})
            pop = props.get("population_covered", "unknown")
            pct = props.get("cumulative_coverage_pct", "unknown")
            site_summaries.append(
                f"  Site {i}: {float(pop):,.0f} people covered "
                f"(cumulative {float(pct):.1f}%)"
                if pop != "unknown" else f"  Site {i}: coverage data unavailable"
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
