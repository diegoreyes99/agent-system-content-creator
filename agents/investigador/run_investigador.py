#!/usr/bin/env python3
"""Corre el agente Investigador por sí solo (Fase 2) y registra la corrida en MLflow.

Uso (desde agents_dopa_final_project/, con el entorno activo — source ~/.venvs/dopa/bin/activate — y LM Studio corriendo):
  python agents/investigador/run_investigador.py --brief baseline/briefs/brief_2026-11_op1_captar-socios.md \
      --prompt-version v6 --trigger t2

Al terminar muestra los temas propuestos y espera la decisión de Dani (punto de
aprobación), en dos preguntas: 1) con qué temas se queda (números, 'ninguno',
'nueva' para otra búsqueda o 'salir'); 2) si quiere agregar temas suyos, tal cual
o pidiendo que el Investigador los investigue. La selección queda en
runs/<fecha>/seleccion.json; es lo único que pasa al Estratega.

Opciones útiles:
  --prompt-version v1   versión del prompt en prompts/investigador_<v>.md
  --temperature 0.3     si no se da, se usa la del servidor (igual que el baseline)
  --trigger t2          mensaje de arranque que pide buscar antes de responder (default: t1)
  --search-backend stub resultados de ejemplo sin internet (default: tavily, o SEARCH_BACKEND del .env)
  --sin-aprobacion      no pide la selección de Dani (para pruebas)
  --no-mlflow           corre sin registrar (para depurar)

Cada corrida guarda en agents/investigador/runs/<fecha>/:
  output.json      salida parseada
  raw.txt          respuesta cruda del modelo
  trace.json       trayectoria: tool calls, resultados, tokens, latencia
  validation.json  errores de esquema, correcciones del código y métricas

Todos los errores del modelo se acumulan además en agents/investigador/model_errors.csv.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
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
from output_checks import (  # noqa: E402
    append_error_log, apply_source_rules, compute_metrics, extract_json, trace_metrics, validate,
)

# Bitácora acumulada de errores del modelo (todas las corridas y evals).
ERROR_LOG = HERE / "model_errors.csv"

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
            f"El Investigador no devolvió texto (modelo {investigador.model_id()}, proveedor {investigador.provider()}). "
            "Con el modelo local, revisa que LM Studio esté corriendo y que LM_STUDIO_MODEL_ID sea el id exacto; "
            "con Gemini, revisa GOOGLE_API_KEY."
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
        json.dumps({"schema_errors": errors, "correcciones": result.get("correcciones", []), "metrics": metrics},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_mlflow_run_id(folder: Path, run) -> None:
    """Guarda el id de la corrida de MLflow junto a sus archivos, para que
    rate_investigador.py pueda registrar ahí las calificaciones humanas."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mlflow_run.json").write_text(json.dumps({"run_id": run.info.run_id}), encoding="utf-8")


def log_to_mlflow(args, run_id: str, run_dir: Path, metrics: dict, temperature) -> None:
    import mlflow

    from tracking import setup_mlflow

    experiment_id = setup_mlflow()
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"investigador-{args.prompt_version}-{args.trigger}-{tools.get_backend()}-{run_id}") as run:
        save_mlflow_run_id(run_dir, run)
        mlflow.log_params({
            "agent": "investigador",
            "prompt_version": args.prompt_version,
            "trigger_version": args.trigger,
            "model": investigador.model_id(),
            "model_provider": investigador.provider(),
            "model_retry_attempts": investigador.retry_attempts(),
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


# --------------------------------------------------------------------------
# Punto de aprobación de Dani (patrón requires_confirmation, Clase 4 Bloque D)
# --------------------------------------------------------------------------
# El Investigador propone; nada pasa al Estratega hasta que Dani elige con qué
# temas se queda (o pide una búsqueda nueva). Hoy es en terminal; en producción
# será por WhatsApp (Fase 6). La selección queda en seleccion.json.
MAX_RONDAS = 3


def evaluate(result: dict, prompt_version: str) -> tuple[dict | None, list[str], dict]:
    try:
        output = extract_json(result["raw"])
        errors = validate(output, prompt_version)
    except (ValueError, json.JSONDecodeError) as exc:
        output, errors = None, [f"JSON no parseable: {exc}"]
    result["correcciones"] = apply_source_rules(output, result["trace"], prompt_version)
    metrics = compute_metrics(output, errors)
    metrics["n_recomendados_corregidos"] = float(len(result["correcciones"]))
    metrics.update(trace_metrics(output, result["trace"]))
    metrics.update({
        "latency_s": round(result["latency_s"], 2),
        "prompt_tokens": float(result["prompt_tokens"]),
        "completion_tokens": float(result["completion_tokens"]),
    })
    return output, errors, metrics


def print_errors(errors: list[str], corrections: list[dict], indent: str = "  ") -> None:
    """Lista en pantalla cada error del modelo: de esquema y correcciones de fuente."""
    for e in errors:
        print(f"{indent}! Esquema: {e}")
    for c in corrections:
        print(f"{indent}! Corregido por el código · tema {c['id']} \"{c['tema']}\": {c['motivo']}")


def print_summary(metrics: dict, errors: list[str], run_dir: Path, corrections: list[dict] | None = None) -> None:
    print(f"\nTool calls: {int(metrics['n_tool_calls'])} · hallazgos: {int(metrics['n_hallazgos'])} "
          f"(alta: {int(metrics['n_alta'])}, recomendados: {int(metrics.get('n_recomendados', 0))}) · "
          f"esquema válido: {'sí' if metrics['schema_valid'] else 'no'} · {metrics['latency_s']} s")
    print_errors(errors, corrections or [])
    print(f"Resultados en {run_dir}")


TIPO_FUENTE_LABELS = {"certificada": "fuente certificada", "web": "fuente web", "red_social": "red social",
                      "competidor": "OTRO GIMNASIO: usar solo la información general, sin citarlo",
                      "no_verificada": "FUENTE NO VERIFICADA"}


def show_topics(output: dict | None, ronda: int, kept: list[dict]) -> list[dict]:
    """Imprime los temas propuestos en esta ronda (y los ya elegidos antes). Regresa los hallazgos."""
    hallazgos = [h for h in (output or {}).get("hallazgos") or [] if isinstance(h, dict)]
    print(f"\n=== Temas propuestos por el Investigador (ronda {ronda}) — esperando a Dani ===")
    if kept:
        print("\n  Ya elegidos en rondas anteriores:")
        for k in kept:
            print(f"    · {k.get('tema', '?')}{'  (tema de Dani)' if k.get('origen') == 'dani' else ''}")
    if not hallazgos:
        print("\n  (El Investigador no propuso ningún tema en esta ronda.)")
    for i, h in enumerate(hallazgos, start=1):
        h.setdefault("id", i)
        mark = "★" if h.get("recomendado") else " "
        print(f"\n {mark} {h['id']}. {h.get('tema', '?')}  [{h.get('prioridad', '?')}]")
        if h.get("que_dice_la_fuente"):
            print(f"      Fuente dice: {h['que_dice_la_fuente']}")
        if h.get("responde_a"):
            print(f"      Responde a: {h['responde_a']}")
        else:
            print(f"      Para DOPA: {h.get('relevancia_dopa', '')}")
        if "tipo_fuente" in h:
            weak = "" if h.get("contenido_suficiente", True) else " · poco contenido"
            print(f"      ({TIPO_FUENTE_LABELS.get(h['tipo_fuente'], h['tipo_fuente'])}{weak})")
        print(f"      {h.get('fuente', '')}")
    if (output or {}).get("resumen_ejecutivo"):
        print(f"\n  Resumen: {output['resumen_ejecutivo']}")
    if hallazgos:
        print("\n  ★ = recomendado por el Investigador")
    return hallazgos


def parse_numbers(answer: str) -> list[int] | None:
    """Lee "1,3,5", "1 3 5" o "1, 2 y 4". Regresa None si hay algo que no sea un número."""
    parts = [p for p in re.split(r"[,\s]+", re.sub(r"\by\b", ",", answer.lower())) if p]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return list(dict.fromkeys(int(p) for p in parts))  # sin repetidos, en el orden en que los escribió


def ask_selection(hallazgos: list[dict], can_search: bool) -> dict:
    """Pregunta 1: con qué temas del Investigador se queda Dani."""
    ids = [h["id"] for h in hallazgos]
    options = "Escribe los números (ej. 1,3,5) o 'ninguno'"
    if can_search:
        options += "; 'nueva' para descartarlos y pedir otra búsqueda"
    options += "; 'salir' para terminar sin aprobar nada"
    while True:
        answer = input(f"\n1) ¿Con qué temas te quedas? {options}: ").strip()
        lower = answer.lower()
        if lower == "salir":
            return {"accion": "salir"}
        if can_search and lower.startswith("nueva"):
            indicaciones = answer.split(":", 1)[1].strip() if ":" in answer else input(
                "   ¿Qué quieres que busque distinto? (Enter si no hay indicaciones): ").strip()
            return {"accion": "nueva", "indicaciones": indicaciones}
        if lower in ("ninguno", "ninguna", "0"):
            return {"accion": "elegir", "ids": []}
        chosen = parse_numbers(answer)
        if chosen is None:
            valid = "números, 'ninguno', 'nueva' o 'salir'" if can_search else "números, 'ninguno' o 'salir'"
            print(f"  Aquí solo van {valid}. "
                  "Si quieres sumar un tema tuyo, elige primero: en la siguiente pregunta lo agregas.")
            continue
        invalid = [c for c in chosen if c not in ids]
        if invalid:
            print(f"  Números no válidos: {invalid}. Opciones: {ids}")
            continue
        return {"accion": "elegir", "ids": chosen}


def ask_own_topics(can_search: bool) -> tuple[list[str], str | None]:
    """Pregunta 2: temas propios de Dani.

    Regresa (temas que se agregan tal cual, tema que Dani quiere que se investigue o None).
    """
    own: list[str] = []
    while True:
        prompt = "\n2) ¿Quieres agregar un tema tuyo? Escríbelo" + (" (otro más)" if own else "") + ", o Enter para terminar: "
        tema = input(prompt).strip()
        if not tema:
            return own, None
        if can_search:
            while True:
                how = input("   ¿Lo agrego tal cual (t) o le pido al Investigador que lo investigue (i)? ").strip().lower()
                if how in ("t", "i"):
                    break
                print("    Escribe t o i.")
            if how == "i":
                return own, tema
        else:
            print("   (Ya no quedan rondas de búsqueda: se agrega tal cual.)")
        own.append(tema)
        print(f"   Agregado: {tema}")


def ask_dani(output: dict | None, ronda: int, kept: list[dict], can_search: bool) -> dict:
    """Muestra los temas propuestos y espera la decisión de Dani. Nunca asume aprobación.

    Son dos preguntas separadas: primero elige entre los temas del Investigador,
    después puede sumar temas suyos (tal cual o pidiendo que se investiguen).
    """
    hallazgos = show_topics(output, ronda, kept)
    while True:
        first = ask_selection(hallazgos, can_search)
        if first["accion"] in ("salir", "nueva"):
            return first
        selected = [{**h, "origen": "investigador", "ronda": ronda} for h in hallazgos if h["id"] in first["ids"]]
        own, to_investigate = ask_own_topics(can_search)
        decision = {"ids": first["ids"], "temas_dani": own,
                    "seleccion": selected + [{"tema": t, "origen": "dani", "ronda": ronda} for t in own]}
        if to_investigate:
            return {"accion": "investigar", "indicaciones": to_investigate, **decision}
        if decision["seleccion"] or kept:
            return {"accion": "aprobar", **decision}
        print("  No elegiste ningún tema ni agregaste uno tuyo. Vuelve a elegir, o escribe 'salir'.")


def build_new_search_note(decision: dict, output: dict | None, kept: list[dict]) -> str:
    previous = [h.get("tema", "") for h in (output or {}).get("hallazgos") or [] if isinstance(h, dict)]
    previous += [k.get("tema", "") for k in kept if k.get("tema") not in previous]
    indicaciones = decision.get("indicaciones", "").rstrip(".")
    if decision["accion"] == "investigar":
        note = (f"\n\nDani pidió investigar este tema suyo: {indicaciones}. "
                "Busca fuentes sobre ese tema y propón hallazgos sobre él.")
    else:
        note = "\n\nDani pidió una búsqueda nueva."
        if indicaciones:
            note += f" Sus indicaciones: {indicaciones}."
    if previous:
        note += " Ya se le propusieron estos temas; no los repitas: " + "; ".join(previous)
    return note


def save_selection(run_dir: Path, decisiones: list[dict], kept: list[dict], sin_aprobacion: bool) -> dict:
    final = decisiones[-1] if decisiones else {}
    if sin_aprobacion:
        status = "sin_aprobacion"
    elif final.get("accion") == "aprobar":
        status = "aprobado"
    else:
        status = "cancelado"  # salió sin aprobar nada
    seleccion = {
        "status": status,
        "ronda_aprobada": final.get("ronda") if status == "aprobado" else None,
        # Lo elegido en rondas anteriores (antes de pedir otra búsqueda) más lo de la ronda final.
        "seleccion": kept + final.get("seleccion", []) if status == "aprobado" else [],
        "historial": [{k: v for k, v in d.items() if k != "seleccion"} for d in decisiones],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "seleccion.json").write_text(json.dumps(seleccion, ensure_ascii=False, indent=2), encoding="utf-8")
    if status == "aprobado":
        n_dani = sum(1 for s in seleccion["seleccion"] if s.get("origen") == "dani")
        print(f"\nAprobado: {len(seleccion['seleccion'])} temas seleccionados ({n_dani} tuyos) → {run_dir / 'seleccion.json'}")
        print("Estos son los temas que recibirá el Estratega.")
    elif status == "cancelado":
        print("\nNo se aprobó ningún tema: el ciclo no avanza al Estratega.")
    return seleccion


def main() -> None:
    parser = argparse.ArgumentParser(description="Corre el Investigador (Fase 2) y lo registra en MLflow.")
    parser.add_argument("--brief", type=Path, required=True, help="Brief del mes (.md)")
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--trigger", choices=sorted(TRIGGERS), default="t1",
                        help="Versión del mensaje de arranque (ver TRIGGERS)")
    parser.add_argument("--model", choices=sorted(investigador.VALID_PROVIDERS), default=None,
                        help="local (LM Studio, default) or gemini (Gemini API, needs GOOGLE_API_KEY)")
    parser.add_argument("--search-backend", choices=sorted(tools.VALID_BACKENDS), default=None)
    parser.add_argument("--sin-aprobacion", action="store_true",
                        help="No pedir la selección de Dani al final (para pruebas)")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    if args.model:
        os.environ["MODEL_PROVIDER"] = args.model
    if investigador.provider() == "gemini" and not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("Missing GOOGLE_API_KEY. Add it to agents/investigador/.env (get one at https://aistudio.google.com).")
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
    run_dir = HERE / "runs" / run_id
    brief_text = args.brief.read_text(encoding="utf-8")
    print(f"=== Investigador {args.prompt_version}/{args.trigger} · modelo {investigador.model_id()} · búsqueda {tools.get_backend()} ===")
    if investigador.provider() == "gemini":
        print(f"    reintentos ante 429/503: {'activos, ' + str(investigador.retry_attempts()) + ' intentos' if investigador.retries_supported() else 'NO disponibles en esta versión de ADK'}")

    # Un solo ciclo asíncrono para todas las rondas: LiteLLM reutiliza su conexión.
    loop = asyncio.new_event_loop()
    trigger = TRIGGERS[args.trigger]
    decisiones: list[dict] = []
    kept: list[dict] = []  # temas elegidos en rondas anteriores, cuando Dani pide otra búsqueda
    first_metrics: dict = {}
    try:
        for ronda in range(1, MAX_RONDAS + 1):
            result = loop.run_until_complete(run_agent(brief_text, args.prompt_version, args.temperature, trigger))
            output, errors, metrics = evaluate(result, args.prompt_version)
            # La ronda 1 queda en la carpeta de la corrida (igual que antes); las nuevas búsquedas, en ronda_N/.
            round_dir = run_dir if ronda == 1 else run_dir / f"ronda_{ronda}"
            save_run(round_dir, result, output, errors, metrics)
            append_error_log(ERROR_LOG, {"origen": "run", "carpeta": str(round_dir.relative_to(HERE)),
                                         "prompt_version": args.prompt_version, "modelo": investigador.model_id(),
                                         "brief": args.brief.name}, errors, result["correcciones"])
            first_metrics = first_metrics or metrics
            print_summary(metrics, errors, round_dir, result["correcciones"])

            if args.sin_aprobacion:
                break
            # En la última ronda ya no se ofrece otra búsqueda.
            decision = ask_dani(output, ronda, kept, can_search=ronda < MAX_RONDAS)
            decisiones.append({"ronda": ronda, **decision})
            if decision["accion"] not in ("nueva", "investigar"):
                break
            trigger = TRIGGERS[args.trigger] + build_new_search_note(decision, output, kept)
            kept += decision.get("seleccion", [])
        else:
            print(f"\nSe alcanzó el máximo de {MAX_RONDAS} rondas de búsqueda.")
    finally:
        loop.close()

    seleccion = save_selection(run_dir, decisiones, kept, args.sin_aprobacion)

    if not args.no_mlflow:
        final_metrics = {**first_metrics,
                         "n_rondas": float(max(1, len(decisiones))),
                         "aprobado": 1.0 if seleccion["status"] == "aprobado" else 0.0,
                         "n_seleccionados": float(len(seleccion["seleccion"]))}
        log_to_mlflow(args, run_id, run_dir, final_metrics, args.temperature)
        print("Corrida registrada en MLflow (experimento 'dopa-investigador').")

if __name__ == "__main__":
    main()
