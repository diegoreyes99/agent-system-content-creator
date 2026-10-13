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


def model_id() -> str:
    # Mismo default que el baseline (run_baseline_cycle.py), para comparar con el mismo modelo.
    return os.environ.get("LM_STUDIO_MODEL_ID", "qwen/qwen3-vl-4b")


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
        # timeout: si LM Studio no responde en 5 min, la corrida falla con error
        # en vez de quedarse esperando para siempre.
        model=LiteLlm(model=f"openai/{model_id()}", timeout=300),
        # Se pasa como función (InstructionProvider) y no como string para que
        # ADK no intente sustituir {llaves} del brief o del JSON de ejemplo
        # con variables de sesión.
        instruction=lambda _ctx: instruction,
        tools=[search_web],
        before_tool_callback=guardrail_before_tool,
        generate_content_config=config,
    )
