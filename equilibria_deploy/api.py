"""
api.py
------
FastAPI backend for Equilibria. Exposes two endpoints:
  GET  /api/health  — liveness check
  POST /api/run     — runs the full Equilibria pipeline

The React frontend calls /api/run with a JSON body {"prompt": "..."}.
CORS is open to all origins so Vercel-hosted frontend can reach this.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── request / response models ────────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt: str


class RunResponse(BaseModel):
    map_html: str = ""
    report_text: str = ""
    validation_warnings: list[str] = []
    chosen_sites_geojson: str = ""
    needs_clarification: bool = False
    clarifying_question: str | None = None
    error: str | None = None


# ── app setup ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Equilibria API starting up…")
    yield
    logger.info("Equilibria API shutting down.")


app = FastAPI(
    title="Equilibria API",
    description="Equity-weighted facility siting agent",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the Vercel frontend (and any other origin) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "message": "Equilibria API is ready."}


@app.post("/api/run", response_model=RunResponse)
async def run_pipeline(body: RunRequest):
    """
    Runs the full seven-agent Equilibria pipeline for the given prompt.
    Returns map HTML, policy brief, validation warnings, and site GeoJSON.
    Long-running — the client should show a loading state.
    """
    logger.info("Received prompt: %s", body.prompt[:100])
    from equilibria.agents.orchestrator import run_equilibria

    result = await run_equilibria(body.prompt)

    return RunResponse(
        map_html=result.map_html,
        report_text=result.report_text,
        validation_warnings=result.validation_warnings,
        chosen_sites_geojson=result.chosen_sites_geojson,
        needs_clarification=result.needs_clarification,
        clarifying_question=result.clarifying_question,
        error=result.error,
    )
