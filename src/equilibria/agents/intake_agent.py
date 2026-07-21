"""
intake_agent.py
----------------
Parses a free-text facility-siting request into a structured IntakeResult
using Groq (llama-3.3-70b-versatile). Returns a plain Python dataclass —
no ADK session machinery needed.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from equilibria.agents.llm_client import chat_json

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"


class EquityWeightHints(BaseModel):
    density: float = Field(default=0.4)
    distance: float = Field(default=0.4)
    road_access: float = Field(default=0.2)


class IntakeResult(BaseModel):
    location_name: str = Field(default="")
    num_sites: int = Field(default=0)
    target_population: str = Field(default="general population")
    budget_per_site: Optional[float] = Field(default=None)
    total_budget: Optional[float] = Field(default=None)
    equity_weight_hints: EquityWeightHints = Field(
        default_factory=EquityWeightHints
    )
    needs_clarification: bool = Field(default=False)
    clarifying_question: Optional[str] = Field(default=None)


SYSTEM_PROMPT = """\
You are a geospatial planning assistant. Extract siting parameters from the
user's request and return ONLY a valid JSON object with these exact keys:

{
    "location_name": "full place name including country, e.g. Kano State, Nigeria",
    "num_sites": <integer, number of new sites requested>,
    "target_population": "who to prioritize, e.g. children under 5",
    "budget_per_site": <number or null>,
    "total_budget": <number or null>,
    "equity_weight_hints": {
        "density": <0.0-1.0, default 0.4>,
        "distance": <0.0-1.0, default 0.4>,
        "road_access": <0.0-1.0, default 0.2>
    },
    "needs_clarification": <true if location OR num_sites is missing>,
    "clarifying_question": "<one question if needs_clarification is true, else null>"
}

Rules:
- ONLY set needs_clarification=true if location_name OR num_sites cannot 
    be determined. NOTHING ELSE should trigger clarification.
- target_population ALWAYS has a default of "general population" — never 
    ask about it, never set needs_clarification because of it.
- budget fields are always optional — never ask about them.
- equity_weight_hints values must sum to 1.0; use defaults if not mentioned.
- Return ONLY the JSON object, no preamble or explanation.

Example input: "We have funding for 5 new vaccination outreach points in Kano State"
Example output:
{
    "location_name": "Kano State, Nigeria",
    "num_sites": 5,
    "target_population": "children eligible for vaccination",
    "budget_per_site": null,
    "total_budget": null,
    "equity_weight_hints": {"density": 0.4, "distance": 0.4, "road_access": 0.2},
    "needs_clarification": false,
    "clarifying_question": null
}
"""


def run_intake_agent(user_request: str) -> IntakeResult:
    """
    Calls Groq to parse the user request into a structured IntakeResult.
    This replaces the ADK LlmAgent — same behaviour, no session overhead.
    """
    logger.info("[IntakeAgent] Parsing request: %s", user_request[:100])
    data = chat_json(SYSTEM_PROMPT, user_request, model=GROQ_MODEL)

    # Sanitise None values before Pydantic validation
    data["target_population"] = data.get("target_population") or "general population"
    data["location_name"] = data.get("location_name") or ""
    data["num_sites"] = data.get("num_sites") or 0
    data["needs_clarification"] = bool(data.get("needs_clarification"))

    # If the model only asked about target_population (which we default),
    # don't block the pipeline on that single missing field.
    # Clear needs_clarification when location and num_sites are present.
    if data["needs_clarification"]:
        has_location = bool(data.get("location_name"))
        has_num_sites = bool(data.get("num_sites")) and int(data.get("num_sites")) > 0
        if has_location and has_num_sites:
            data["needs_clarification"] = False
            data["clarifying_question"] = None

    # Ensure equity weights sum to 1.0
    hints = data.get("equity_weight_hints", {})
    total = sum([
        hints.get("density", 0.4),
        hints.get("distance", 0.4),
        hints.get("road_access", 0.2),
    ])
    if total > 0 and abs(total - 1.0) > 0.01:
        for k in hints:
            hints[k] = round(hints[k] / total, 4)
        data["equity_weight_hints"] = hints

    result = IntakeResult.model_validate(data)
    logger.info(
        "[IntakeAgent] Done — location=%s, num_sites=%d, clarification=%s",
        result.location_name, result.num_sites, result.needs_clarification,
    )
    return result
