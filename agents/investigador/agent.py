"""Definición del agente Investigador en Google ADK.

Se separa de run_investigador.py para que el mismo agente se pueda importar
después desde el Orquestador (o desde un eval) sin arrastrar la lógica de
corrida y de MLflow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from tools import search_web

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # agents_dopa_final_project/
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Mínimo privilegio (Clase 4, Bloque A): el Investigador solo puede usar
# estas herramientas, y todas son de lectura. Si algún día se le agrega una
# herramienta de escritura, NO va en esta lista: necesitaría el patrón de
# confirmación humana (requires_confirmation).
READ_ONLY_TOOLS = {"search_web"}
MAX_SEARCH_CALLS = 5


# Model provider: "local" (LM Studio, OpenAI-compatible) or "gemini" (Gemini API).
# Selected with MODEL_PROVIDER or with --model in run_investigador.py / eval_investigador.py.
VALID_PROVIDERS = {"local", "gemini"}
DEFAULT_GEMINI_MODEL_ID = "gemini-3.1-flash-lite"  # same model family used in Class 4

# Retries with exponential backoff for Gemini (Class 7 pattern). Google answers
# 429 when we exceed the per-minute quota and 503 when the model is overloaded;
# both are temporary, so instead of losing the run we wait and try again:
# 5 s, 10 s, 20 s, 40 s (plus a little random jitter), then give up.
GEMINI_RETRY_ATTEMPTS = 5  # first try + 4 retries
GEMINI_RETRY_STATUS_CODES = [408, 429, 500, 502, 503, 504]


def provider() -> str:
    value = os.environ.get("MODEL_PROVIDER", "local").strip().lower()
    if value not in VALID_PROVIDERS:
        raise ValueError(f"MODEL_PROVIDER='{value}' is not valid. Options: {sorted(VALID_PROVIDERS)}")
    return value


def model_id() -> str:
    if provider() == "gemini":
        return os.environ.get("GEMINI_MODEL_ID", DEFAULT_GEMINI_MODEL_ID)
    # Mismo default que el baseline (run_baseline_cycle.py), para comparar con el mismo modelo.
    return os.environ.get("LM_STUDIO_MODEL_ID", "qwen/qwen3-vl-4b")


def retries_supported() -> bool:
    """True if this ADK version accepts retry_options on its Gemini model."""
    return "retry_options" in getattr(Gemini, "model_fields", {})


def retry_attempts() -> int:
    """Attempts per model call (1 = no retries). Logged to MLflow."""
    return GEMINI_RETRY_ATTEMPTS if provider() == "gemini" and retries_supported() else 1


def build_model():
    """Gemini is native to ADK; the local model goes through LiteLLM."""
    if provider() == "gemini":
        # Use the Gemini API with GOOGLE_API_KEY, not Vertex AI.
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
        if not retries_supported():
            return model_id()
        return Gemini(
            model=model_id(),
            retry_options=types.HttpRetryOptions(
                attempts=GEMINI_RETRY_ATTEMPTS,
                initial_delay=5.0,
                max_delay=60.0,
                exp_base=2.0,
                jitter=1.0,
                http_status_codes=GEMINI_RETRY_STATUS_CODES,
            ),
        )
    # timeout: si LM Studio no responde en 5 min, la corrida falla con error
    # en vez de quedarse esperando para siempre.
    return LiteLlm(model=f"openai/{model_id()}", timeout=300)


def prompt_path(prompt_version: str) -> Path:
    return PROMPTS_DIR / f"investigador_{prompt_version}.md"


def load_instruction(prompt_version: str, brief_text: str) -> str:
    """Lee el prompt versionado y mete el brief en el bloque DATOS."""
    text = prompt_path(prompt_version).read_text(encoding="utf-8")
    return text.replace("{brief_del_mes}", brief_text)


def guardrail_before_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """before_tool_callback (Clase 4, Bloque B · "aquí vive la v0.4").

    Se ejecuta en código antes de cada tool call. Si regresa un dict, ADK NO
    ejecuta la herramienta y le pasa ese dict al modelo como resultado:
    falla cerrada, con un error estructurado en vez de una excepción.
    """
    if tool.name not in READ_ONLY_TOOLS:
        return {"status": "error", "error_code": "TOOL_NOT_ALLOWED", "tool": tool.name}

    calls = tool_context.state.get("search_calls", 0) + 1
    tool_context.state["search_calls"] = calls
    if calls > MAX_SEARCH_CALLS:
        return {
            "status": "error",
            "error_code": "SEARCH_LIMIT_REACHED",
            "detail": f"Máximo {MAX_SEARCH_CALLS} búsquedas por corrida. Reporta con lo que ya tienes.",
        }
    return None  # None = deja que la herramienta corra normal


def build_agent(
    brief_text: str,
    prompt_version: str = "v1",
    temperature: Optional[float] = None,
) -> Agent:
    instruction = load_instruction(prompt_version, brief_text)

    config = None
    if temperature is not None:
        config = types.GenerateContentConfig(temperature=temperature)

    return Agent(
        name="investigador",
        model=build_model(),
        # Se pasa como función (InstructionProvider) y no como string para que
        # ADK no intente sustituir {llaves} del brief o del JSON de ejemplo
        # con variables de sesión.
        instruction=lambda _ctx: instruction,
        tools=[search_web],
        before_tool_callback=guardrail_before_tool,
        generate_content_config=config,
    )
