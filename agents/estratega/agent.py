"""The Estratega agent in Google ADK (definition only; runs live in run_estratega.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
sys.path.insert(0, str(HERE.parent / "shared"))

from models import build_gemini, retries_supported, GEMINI_RETRY_ATTEMPTS  # noqa: E402
from tools import get_month_calendar, search_dopa_knowledge  # noqa: E402

# Candidates compared in the eval (decision 2026-10-26: start with Gemini).
#   gemini-3.5-flash-lite: baseline, same as the Investigador.
#   gemini-3.8-flash: more capable, for planning with many rules.
DEFAULT_MODEL_ID = "gemini-3.5-flash-lite"

# Least privilege (Class 4, Block A): only read-only tools, each with a cap.
TOOL_LIMITS = {"get_month_calendar": 2, "search_dopa_knowledge": 6}


def model_id() -> str:
    return os.environ.get("ESTRATEGA_MODEL_ID", DEFAULT_MODEL_ID)


def retry_attempts() -> int:
    return GEMINI_RETRY_ATTEMPTS if retries_supported() else 1


def prompt_path(prompt_version: str) -> Path:
    return PROMPTS_DIR / f"estratega_{prompt_version}.md"


def guardrail_before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    """Runs in code before every tool call. A returned dict replaces the tool
    result: fails closed with a structured error, never an exception."""
    if tool.name not in TOOL_LIMITS:
        return {"status": "error", "error_code": "TOOL_NOT_ALLOWED", "tool": tool.name}
    key = f"calls_{tool.name}"
    calls = tool_context.state.get(key, 0) + 1
    tool_context.state[key] = calls
    if calls > TOOL_LIMITS[tool.name]:
        return {"status": "error", "error_code": "TOOL_LIMIT_REACHED",
                "detail": f"Máximo {TOOL_LIMITS[tool.name]} llamadas a {tool.name}. Continúa con lo que ya tienes."}
    return None


def build_agent(instruction: str, temperature: Optional[float] = None) -> Agent:
    config = types.GenerateContentConfig(temperature=temperature) if temperature is not None else None
    return Agent(
        name="estratega",
        model=build_gemini(model_id()),
        # A function (InstructionProvider), not a string, so ADK does not try to
        # replace {braces} in the brief or the JSON examples with session state.
        instruction=lambda _ctx: instruction,
        tools=[get_month_calendar, search_dopa_knowledge],
        before_tool_callback=guardrail_before_tool,
        generate_content_config=config,
    )
