#!/usr/bin/env python3
"""
Baseline de referencia -- Fase 1, Sistema de Agentes de Marketing DOPA.

Corre los 6 prompts de agentes (Orquestador, Investigador, Estratega,
Copywriter, Disenador, Analista) en secuencia contra un modelo servido
localmente por LM Studio, usando las clases de Google ADK (Agent + LiteLlm)
como mecanismo uniforme de llamada al modelo.

Esto es un EJERCICIO PUNTUAL de baseline (Fase 1 de GUIA_DE_IMPLEMENTACION.md),
no el sistema en operacion continua. Nada se "publica" de verdad -- sirve
como punto de comparacion para cuando en la Fase 2 se construya el primer
agente real en ADK.

Requisitos antes de correr (ver README.md de esta carpeta para el detalle):
  1. LM Studio corriendo con un modelo cargado y su servidor local activo
     (normalmente http://localhost:1234/v1 -- verifica el puerto exacto en
     la pestana "Developer" / "Local Server" de LM Studio).
  2. El identificador EXACTO del modelo tal como LM Studio lo expone (se ve
     en esa misma pestana) puesto en la variable de entorno
     LM_STUDIO_MODEL_ID, o editado abajo en DEFAULT_MODEL_ID.
  3. pip install -r requirements.txt (idealmente dentro de un entorno
     virtual fuera de Documents: python3 -m venv ~/.venvs/dopa && source ~/.venvs/dopa/bin/activate).

Uso:
  python run_baseline_cycle.py --brief briefs/ciclo-1-brief.md

Nota sobre el Analista de Resultados: no corre dentro de este ciclo hacia
adelante, porque necesita metricas reales de Instagram de un ciclo YA
publicado (que todavia no existe en un baseline). Correrlo por separado
cuando haya metricas reales -- ver run_analista_standalone() al final de
este archivo.

Hallazgo pendiente de resolver (no se corrigio aqui para no tocar los
prompts sin que lo decidas tu): el prompt del Estratega (estratega_v1.md)
menciona en su CONTEXTO que debe considerar "los insights del Analista del
ciclo anterior", pero su bloque DATOS no tiene un placeholder para
recibirlos -- solo {hallazgos_investigador} y {brief_del_mes}. Hoy no hay
forma de pasarle al Estratega los insights del Analista de forma
programada. Si quieres, en otra sesion le agregamos ese placeholder al
prompt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv es opcional; si no esta, usa solo variables de entorno del shell.

# --------------------------------------------------------------------------
# Configuracion de LM Studio (servidor local compatible con OpenAI)
# --------------------------------------------------------------------------
DEFAULT_MODEL_ID = "qwen/qwen3-vl-4b"  # <- verifica el id real en LM Studio y ajustalo
LM_STUDIO_MODEL_ID = os.environ.get("LM_STUDIO_MODEL_ID", DEFAULT_MODEL_ID)
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:1234/v1")
os.environ.setdefault("OPENAI_API_KEY", "lm-studio")  # LM Studio no valida la key, solo exige que exista

MODEL = LiteLlm(model=f"openai/{LM_STUDIO_MODEL_ID}")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CYCLES_DIR = Path(__file__).resolve().parent / "cycles"

APP_NAME = "dopa_baseline"
USER_ID = "diego"


def load_prompt(filename: str, **variables: str) -> str:
    """Lee un prompt .md y sustituye los placeholders {var} del bloque DATOS."""
    text = (PROMPTS_DIR / filename).read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace("{" + key + "}", value)
    return text


def extract_json(raw_text: str) -> dict:
    """Extrae el primer bloque JSON valido de la respuesta del modelo.

    Los modelos pequenos a veces envuelven el JSON en texto explicativo o en
    un bloque ```json ... ```. Esta funcion intenta encontrarlo sin asumir
    que la respuesta es JSON puro.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw_text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(
            f"No se encontro un bloque JSON en la respuesta del modelo:\n\n{raw_text}"
        )
    return json.loads(candidate[start : end + 1])


async def call_agent(name: str, instruction: str, trigger: str) -> tuple[str, dict]:
    """Crea un agente ADK desechable con esta instruccion y devuelve (texto_crudo, json_parseado).

    Cada llamada arma un Agent nuevo porque cada paso del ciclo (Investigador,
    Estratega, etc.) tiene datos distintos ya insertados en su instruccion --
    no reusamos el mismo agente con historial de conversacion.
    """
    agent = Agent(model=MODEL, name=name, instruction=instruction)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session_id = f"{name}-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=trigger)])
    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=message
    ):
        if event.content and event.content.parts and not event.partial:
            for part in event.content.parts:
                if part.text:
                    final_text += part.text

    await runner.close()

    if not final_text.strip():
        raise RuntimeError(
            f"El agente '{name}' no devolvio texto. Revisa que LM Studio este "
            f"corriendo y que LM_STUDIO_MODEL_ID='{LM_STUDIO_MODEL_ID}' sea el id "
            "exacto del modelo cargado (pestana Developer de LM Studio)."
        )

    parsed = extract_json(final_text)
    return final_text, parsed


def save_step(cycle_dir: Path, step_name: str, raw_text: str, parsed: dict) -> None:
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / f"{step_name}.raw.txt").write_text(raw_text, encoding="utf-8")
    (cycle_dir / f"{step_name}.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  -> guardado en {cycle_dir / (step_name + '.json')}")


def confirm(prompt: str) -> bool:
    """Punto de aprobacion humana -- replica los 'DETENTE aqui' del Orquestador."""
    answer = input(f"\n{prompt} [s/n]: ").strip().lower()
    return answer in ("s", "si", "y", "yes")


async def run_cycle(brief_path: Path) -> None:
    brief_text = brief_path.read_text(encoding="utf-8")
    cycle_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    cycle_dir = CYCLES_DIR / cycle_id

    print(f"=== Ciclo de referencia {cycle_id} -- modelo: {LM_STUDIO_MODEL_ID} ===")

    # 1. Investigador
    print("\n[1/4] Investigador...")
    instruction = load_prompt("investigador_v1.md", brief_del_mes=brief_text)
    raw, hallazgos = await call_agent(
        "investigador", instruction, "Genera tu salida en el formato JSON indicado."
    )
    save_step(cycle_dir, "01_investigador", raw, hallazgos)

    # 2. Estratega
    print("\n[2/4] Estratega...")
    instruction = load_prompt(
        "estratega_v1.md",
        hallazgos_investigador=json.dumps(hallazgos, ensure_ascii=False),
        brief_del_mes=brief_text,
    )
    raw, parrilla = await call_agent(
        "estratega", instruction, "Genera tu salida en el formato JSON indicado."
    )
    save_step(cycle_dir, "02_estratega", raw, parrilla)

    piezas = parrilla.get("piezas", [])
    print(f"\nParrilla propuesta: {len(piezas)} piezas.")
    print(json.dumps(parrilla, ensure_ascii=False, indent=2))
    if not confirm("Apruebas esta parrilla para continuar con copy y diseno?"):
        print("Ciclo detenido en el primer punto de aprobacion. Nada mas se genero.")
        return

    # 3. Copywriter + Disenador, pieza por pieza
    print("\n[3/4] Copywriter + Disenador...")
    piezas_con_copy = []
    for i, pieza in enumerate(piezas, start=1):
        print(f"  Pieza {i}/{len(piezas)}: {pieza.get('id', '?')}")

        instruction = load_prompt(
            "copywriter_v1.md", pieza_de_la_parrilla=json.dumps(pieza, ensure_ascii=False)
        )
        raw, copy = await call_agent(
            "copywriter", instruction, "Genera tu salida en el formato JSON indicado."
        )
        save_step(cycle_dir, f"03_copywriter_{pieza.get('id', i)}", raw, copy)

        pieza_con_copy = {**pieza, **copy}
        instruction = load_prompt(
            "disenador_v1.md", pieza_con_copy=json.dumps(pieza_con_copy, ensure_ascii=False)
        )
        raw, diseno = await call_agent(
            "disenador", instruction, "Genera tu salida en el formato JSON indicado."
        )
        save_step(cycle_dir, f"03_disenador_{pieza.get('id', i)}", raw, diseno)

        piezas_con_copy.append({"pieza": pieza, "copy": copy, "diseno": diseno})

    print("\nCopys y direccion creativa generados para todas las piezas.")
    if not confirm("Apruebas copys + direccion visual para cerrar el ciclo?"):
        print("Ciclo detenido en el segundo punto de aprobacion.")
        return

    # 4. Orquestador -- reporte de cierre
    print("\n[4/4] Orquestador (reporte de cierre)...")
    instruction = load_prompt("orquestador_v1.md", brief_del_mes=brief_text)
    trigger = (
        "Cierra el ciclo. Se generaron "
        f"{len(piezas_con_copy)} piezas, todas aprobadas en ambos puntos de "
        "control. No se tiene conteo exacto de tokens de este ejercicio "
        "manual -- reportalo como 'no medido en este baseline'."
    )
    raw, cierre = await call_agent("orquestador", instruction, trigger)
    save_step(cycle_dir, "04_orquestador_cierre", raw, cierre)

    print(f"\n=== Ciclo {cycle_id} completo. Resultados en {cycle_dir} ===")


async def run_analista_standalone(metrics_path: Path) -> None:
    """Corre solo al Analista, cuando ya tengas metricas reales de un ciclo publicado.

    No forma parte de run_cycle() porque el primer ciclo de baseline no tiene
    un ciclo anterior del cual sacar metricas.
    """
    metrics_text = metrics_path.read_text(encoding="utf-8")
    instruction = load_prompt("analista_v1.md", metricas_del_ciclo=metrics_text)
    raw, insights = await call_agent(
        "analista", instruction, "Genera tu salida en el formato JSON indicado."
    )
    cycle_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    cycle_dir = CYCLES_DIR / f"{cycle_id}_analista"
    save_step(cycle_dir, "analista", raw, insights)
    print(f"\n=== Analisis completo. Resultado en {cycle_dir} ===")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--brief",
        type=Path,
        help="Ruta al .md con el brief del mes (ver briefs/brief_template.md). Corre el ciclo completo.",
    )
    group.add_argument(
        "--metrics",
        type=Path,
        help="Ruta a un .md/.txt con metricas de un ciclo ya publicado. Corre solo al Analista.",
    )
    args = parser.parse_args()

    if args.brief:
        if not args.brief.exists():
            sys.exit(f"No se encontro el brief: {args.brief}")
        asyncio.run(run_cycle(args.brief))
    else:
        if not args.metrics.exists():
            sys.exit(f"No se encontraron las metricas: {args.metrics}")
        asyncio.run(run_analista_standalone(args.metrics))


if __name__ == "__main__":
    main()



