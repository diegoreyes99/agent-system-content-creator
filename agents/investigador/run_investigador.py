#!/usr/bin/env python3
"""Corre el agente Investigador por sí solo (Fase 2) y registra la corrida en MLflow.

Uso (desde agents_dopa_final_project/, con el .venv activo y LM Studio corriendo):
  python agents/investigador/run_investigador.py --brief baseline/briefs/ciclo-1-brief.md

Opciones útiles:
  --prompt-version v1   versión del prompt en prompts/investigador_<v>.md
  --temperature 0.3     si no se da, se usa la del servidor (igual que el baseline)
  --trigger t2          mensaje de arranque que pide buscar antes de responder (default: t1)
  --search-backend stub resultados de ejemplo sin internet (default: tavily, o SEARCH_BACKEND del .env)
  --no-mlflow           corre sin registrar (para depurar)

Cada corrida guarda en agents/investigador/runs/<fecha>/:
  output.json      salida parseada
  raw.txt          respuesta cruda del modelo
  trace.json       trayectoria: tool calls, resultados, tokens, latencia
  validation.json  errores de esquema + métricas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # para importar agent/tools/output_checks como módulos locales

PROJECT_ROOT = HERE.parents[1]

try:
    from dotenv import load_dotenv

    # Primero el .env de este agente, luego el de la raíz, luego el del baseline.
    # load_dotenv no pisa variables ya definidas, así que gana el primero que exista.
    for env_file in (HERE / ".env", PROJECT_ROOT / ".env", PROJECT_ROOT / "baseline" / ".env"):
        if env_file.exists():
            load_dotenv(env_file)
except ImportError:
    pass

os.environ.setdefault("OPENAI_API_BASE", "http://localhost:1234/v1")
os.environ.setdefault("OPENAI_API_KEY", "lm-studio")  # LM Studio no valida la key
# LiteLLM descarga de internet una tabla de precios de modelos cada vez que se
# importa. Con un modelo local no sirve de nada y puede trabar el arranque:
# usamos la copia que ya viene dentro del paquete.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from google.adk import version as adk_version  # noqa: E402
from google.adk.agents.run_config import RunConfig  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

import agent as investigador  # noqa: E402
import tools  # noqa: E402
from output_checks import compute_metrics, extract_json, validate  # noqa: E402

APP_NAME = "dopa_investigador"
USER_ID = "diego"
MAX_LLM_CALLS = 10  # freno contra bucles de tool calls (Clase 4, Bloque B · RunConfig)
# Mensaje de arranque (el turno del usuario). Se versiona igual que el prompt y
# se registra en MLflow, porque también cambia el comportamiento del agente.
#   t1: el mismo del baseline. Pide el JSON directo, y con él el modelo nunca
#       llamó a search_web (corridas v1 y v2 del 2026-10-12: 0 tool calls).
#   t2: le pide seguir su PROCESO: primero buscar, después entregar el JSON.
TRIGGERS = {
    "t1": "Genera tu salida en el formato JSON indicado.",
    "t2": (
        "Investiga el objetivo del mes que está en DATOS siguiendo tu PROCESO: "
        "primero haz tus búsquedas con search_web y, cuando tengas los resultados, "
        "entrega tu salida en el formato JSON indicado."
    ),
}


async def run_agent(brief_text: str, prompt_version: str, temperature: float | None, trigger: str) -> dict:
    agent = investigador.build_agent(brief_text, prompt_version, temperature)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session_id = f"investigador-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)

    trace: list[dict] = []
    final_text = ""
    prompt_tokens = completion_tokens = 0
    started = time.perf_counter()

    message = types.Content(role="user", parts=[types.Part(text=trigger)])
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=message,
        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
    ):
        if event.partial:
            continue
        if event.usage_metadata:
            prompt_tokens += event.usage_metadata.prompt_token_count or 0
            completion_tokens += event.usage_metadata.candidates_token_count or 0
        for call in event.get_function_calls():
            trace.append({"type": "tool_call", "tool": call.name, "args": dict(call.args or {})})
        for resp in event.get_function_responses():
            trace.append({"type": "tool_result", "tool": resp.name, "response": resp.response})
        if event.is_final_response() and event.content and event.content.parts:
            final_text += "".join(p.text for p in event.content.parts if p.text)

    latency = time.perf_counter() - started
    await runner.close()

    if not final_text.strip():
        raise RuntimeError(
            "El Investigador no devolvió texto. Revisa que LM Studio esté corriendo y que "
            f"LM_STUDIO_MODEL_ID='{investigador.model_id()}' sea el id exacto del modelo cargado."
        )

    return {
        "raw": final_text,
        "trace": trace,
        "latency_s": latency,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def save_run(run_dir: Path, result: dict, output: dict | None, errors: list[str], metrics: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw.txt").write_text(result["raw"], encoding="utf-8")
    (run_dir / "trace.json").write_text(
        json.dumps(
            {k: result[k] for k in ("trace", "latency_s", "prompt_tokens", "completion_tokens")},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    if output is not None:
        (run_dir / "output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "validation.json").write_text(
        json.dumps({"schema_errors": errors, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def log_to_mlflow(args, run_id: str, run_dir: Path, metrics: dict, temperature) -> None:
    import mlflow

    from tracking import setup_mlflow

    experiment_id = setup_mlflow()
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"investigador-{args.prompt_version}-{args.trigger}-{tools.get_backend()}-{run_id}"):
        mlflow.log_params({
            "agent": "investigador",
            "prompt_version": args.prompt_version,
            "trigger_version": args.trigger,
            "model": investigador.model_id(),
            "temperature": "default" if temperature is None else temperature,
            "search_backend": tools.get_backend(),
            "tools_version": tools.TOOLS_VERSION,
            "search_min_score": tools.get_min_score(),
            "tools": ",".join(sorted(investigador.READ_ONLY_TOOLS)),
            "max_search_calls": investigador.MAX_SEARCH_CALLS,
            "max_llm_calls": MAX_LLM_CALLS,
            "brief": args.brief.name,
        })
        mlflow.set_tags({
            "fase": "fase-2",
            "adk_version": adk_version.__version__,
            "hardware": f"{platform.system()}-{platform.machine()}",
        })
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(investigador.prompt_path(args.prompt_version)), "inputs")
        mlflow.log_artifact(str(args.brief), "inputs")
        mlflow.log_artifacts(str(run_dir), "outputs")


def main() -> None:
    parser = argparse.ArgumentParser(description="Corre el Investigador (Fase 2) y lo registra en MLflow.")
    parser.add_argument("--brief", type=Path, required=True, help="Brief del mes (.md)")
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--trigger", choices=sorted(TRIGGERS), default="t1",
                        help="Versión del mensaje de arranque (ver TRIGGERS)")
    parser.add_argument("--search-backend", choices=sorted(tools.VALID_BACKENDS), default=None)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    if args.search_backend:
        os.environ["SEARCH_BACKEND"] = args.search_backend
    if tools.get_backend() == "tavily" and not os.environ.get("TAVILY_API_KEY"):
        sys.exit("Falta TAVILY_API_KEY. Copia agents/investigador/.env.example a .env y pon tu key, "
                 "o corre con --search-backend stub.")
    if not args.brief.exists():
        sys.exit(f"No se encontró el brief: {args.brief}")
    if not investigador.prompt_path(args.prompt_version).exists():
        sys.exit(f"No existe el prompt: {investigador.prompt_path(args.prompt_version)}")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    print(f"=== Investigador {args.prompt_version}/{args.trigger} · modelo {investigador.model_id()} · búsqueda {tools.get_backend()} ===")

    result = asyncio.run(run_agent(args.brief.read_text(encoding="utf-8"), args.prompt_version, args.temperature, TRIGGERS[args.trigger]))

    try:
        output = extract_json(result["raw"])
        errors = validate(output)
    except (ValueError, json.JSONDecodeError) as exc:
        output, errors = None, [f"JSON no parseable: {exc}"]

    metrics = compute_metrics(output, errors)
    metrics.update({
        "n_tool_calls": float(sum(1 for t in result["trace"] if t["type"] == "tool_call")),
        "latency_s": round(result["latency_s"], 2),
        "prompt_tokens": float(result["prompt_tokens"]),
        "completion_tokens": float(result["completion_tokens"]),
    })

    run_dir = HERE / "runs" / run_id
    save_run(run_dir, result, output, errors, metrics)

    print(f"\nTool calls: {int(metrics['n_tool_calls'])} · hallazgos: {int(metrics['n_hallazgos'])} "
          f"(alta: {int(metrics['n_alta'])}) · esquema válido: {'sí' if metrics['schema_valid'] else 'no'} "
          f"· {metrics['latency_s']} s")
    for e in errors:
        print(f"  ! {e}")
    print(f"Resultados en {run_dir}")

    if not args.no_mlflow:
        log_to_mlflow(args, run_id, run_dir, metrics, args.temperature)
        print("Corrida registrada en MLflow (experimento 'dopa-investigador').")


if __name__ == "__main__":
    main()
