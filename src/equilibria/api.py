from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "message": "Equilibria API is ready."}


@app.post("/api/run", response_model=RunResponse)
async def run_pipeline(body: RunRequest) -> RunResponse:
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
