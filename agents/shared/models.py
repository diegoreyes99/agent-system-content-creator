"""Gemini models with retries, shared by the agents built after the Investigador.

(The Investigador keeps its own copy in agents/investigador/agent.py; it can
move here when it is touched again.)
"""

from __future__ import annotations

import os

from google.adk.models.google_llm import Gemini
from google.genai import types

# Retries with exponential backoff (Class 7 pattern): 429 = per-minute quota,
# 503 = model overloaded. Both are temporary: wait 5, 10, 20, 40 s and retry.
GEMINI_RETRY_ATTEMPTS = 5
GEMINI_RETRY_STATUS_CODES = [408, 429, 500, 502, 503, 504]


def retries_supported() -> bool:
    return "retry_options" in getattr(Gemini, "model_fields", {})


def build_gemini(model_id: str):
    """A Gemini model for ADK, through the Gemini API (GOOGLE_API_KEY), with retries."""
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
    if not retries_supported():
        return model_id
    return Gemini(
        model=model_id,
        retry_options=types.HttpRetryOptions(
            attempts=GEMINI_RETRY_ATTEMPTS, initial_delay=5.0, max_delay=60.0, exp_base=2.0, jitter=1.0,
            http_status_codes=GEMINI_RETRY_STATUS_CODES,
        ),
    )
