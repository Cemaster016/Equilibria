"""
llm_client.py
--------------
Shared Groq client used by all three LLM-dependent agents (IntakeAgent,
ValidatorAgent, ReportAgent). Reads GROQ_API_KEY from the environment.

Using Groq instead of Gemini/ADK for these agents because:
  - 14,400 free requests/day vs Gemini's 1,500
  - 30 RPM rate limit vs Gemini's 10 RPM
  - No quota exhaustion mid-pipeline
  - OpenAI-compatible API — simple, well-understood interface
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from groq import Groq

logger = logging.getLogger(__name__)

# Groq's most capable free model as of June 2026
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file.\n"
            "Get a free key (no credit card) at https://console.groq.com"
        )
    return Groq(api_key=api_key)


def chat(
    system: str,
    user: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_retries: int = 3,
    json_mode: bool = False,
) -> str:
    """
    One-shot chat call with automatic retry on rate-limit (429) errors.
    Returns the model's response content as a plain string.
    """
    client = get_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:
            wait = 30 * (2 ** attempt)
            if "429" in str(exc) or "rate" in str(exc).lower():
                logger.warning(
                    "Groq rate limit hit (attempt %d/%d) — waiting %ds",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"Groq call failed after {max_retries} retries.")


def chat_json(system: str, user: str, **kwargs) -> dict:
    """Like chat() but parses and returns the response as a dict."""
    raw = chat(system, user, json_mode=True, **kwargs)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap JSON in markdown fences despite json_mode
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from model response:\n{raw[:500]}")
