"""
config.py
---------
Shared runtime configuration for all Equilibria agents.

Set EQUILIBRIA_LLM_MODEL in your .env to override the default model.
The default is gemini-2.0-flash which has 1 500 free-tier requests/day
vs. 20/day for gemini-3.5-flash.
"""

from __future__ import annotations

import os

DEFAULT_MODEL: str = os.getenv("EQUILIBRIA_LLM_MODEL", "gemini-2.0-flash")
