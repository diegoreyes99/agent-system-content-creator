#!/usr/bin/env python3
"""Runs the Estratega (brief + topics approved by Dani -> content grid) and logs it to MLflow.

Usage (from agents_dopa_final_project/, with the environment active):
  python agents/estratega/run_estratega.py \\
      --brief baseline/briefs/brief_2026-11_op1_captar-socios.md \\
      --seleccion agents/investigador/runs/<fecha>/seleccion.json

Then the grid is written to the "Parrilla DOPA" Google Sheet (one tab per
month). Dani marks each piece's "Estado" (Aprobado / Cambios / Descartado) and
writes comments; you press Enter and the program reads her decisions. Pieces
in "Cambios" are redone with her comment (up to 3 rounds). The approved grid is
saved in runs/<fecha>/parrilla.json: that is what the Copywriter receives.

Useful options:
  --model-id gemini-3.8-flash   model to use (default ESTRATEGA_MODEL_ID or gemini-3.5-flash-lite)
  --prompt-version v5           prompt in prompts/estratega_<v>.md
  --sheet-tab "2026-11 prueba"  tab name (default: the month)
  --sin-aprobacion              no Sheet, no approval (for quick tests)
  --desde-corrida runs/<fecha>  skip the model: send that run's grid to the Sheet for approval
  --no-mlflow                   do not log the run

Each run saves in agents/estratega/runs/<fecha>/: output.json, raw.txt,
trace.json, validation.json, inputs.json and, with approval, parrilla.json.
Every validation error is also appended to agents/estratega/model_errors.csv.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "shared"))

try:
    from dotenv import load_dotenv

    # This agent's .env, then the shared one, then the Investigador's (GOOGLE_API_KEY
    # already lives there). load_dotenv never overwrites, so the first one wins.
    for env_file in (HERE / ".env", PROJECT_ROOT / "agents" / "shared" / ".env",
                     PROJECT_ROOT / "agents" / "investigador" / ".env"):
        if env_file.exists():
            load_dotenv(env_file)
except ImportError:
    pass

from google.adk import version as adk_version  # noqa: E402
from google.adk.agents.run_config import RunConfig  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

import agent as estratega  # noqa: E402
import inputs as estratega_inputs  # noqa: E402
import tools  # noqa: E402
from output_checks import append_error_log, compute_metrics, extract_json, trace_metrics, validate  # noqa: E402

ERROR_LOG = HERE / "model_errors.csv"
APP_NAME = "dopa_estratega"
USER_ID = "diego"
MAX_LLM_CALLS = 14  # 2 calendar + up to 6 searches + answer, with room to spare
MAX_ROUNDS = 3
MLFLOW_EXPERIMENT = "dopa-estratega"

TRIGGER = ("Construye la parrilla del mes que está en DATOS siguiendo tu PROCESO: primero consulta el "
           "calendario y el conocimiento de DOPA con tus herramientas y, cuando tengas lo necesario, "
           "entrega tu salida en el formato JSON indicado.")


async def run_agent(instruction: str, message: str, temperature: float | None) -> dict:
    agent = estratega.build_agent(instruction, temperature)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session_id = f"estratega-{uuid.uuid4().hex[:8]}"
    await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    trace, final_text = [], ""
    prompt_tokens = completion_tokens = 0
    started = time.perf_counter()
    async for event in runner.run_async(user_id=USER_ID, session_id=session_id,
                                        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
                                        run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
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
        raise RuntimeError(f"El Estratega no devolvió texto (modelo {estratega.model_id()}). Revisa GOOGLE_API_KEY.")
    return {"raw": final_text, "trace": trace, "latency_s": latency,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


def evaluate(result: dict, inputs: dict) -> tuple[dict | None, list[str], dict]:
    try:
        output = extract_json(result["raw"])
        errors = validate(output, inputs)
    except (ValueError, json.JSONDecodeError) as exc:
        output, errors = None, [f"JSON no parseable: {exc}"]
    metrics = compute_metrics(output, errors, inputs)
    metrics.update(trace_metrics(result["trace"]))
    metrics.update({"latency_s": round(result["latency_s"], 2), "prompt_tokens": float(result["prompt_tokens"]),
                    "completion_tokens": float(result["completion_tokens"])})
    return output, errors, metrics


def save_run(run_dir: Path, result: dict, output: dict | None, errors: list[str], metrics: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw.txt").write_text(result["raw"], encoding="utf-8")
    (run_dir / "trace.json").write_text(json.dumps(
        {k: result[k] for k in ("trace", "latency_s", "prompt_tokens", "completion_tokens")},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if output is not None:
        (run_dir / "output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({"errors": errors, "metrics": metrics},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(output: dict | None, errors: list[str], metrics: dict, run_dir: Path) -> None:
    if output:
        print(f"\nEstrategia: {output.get('estrategia_del_mes', '')}")
        print(f"Volumen: {output.get('criterio_de_volumen', '')}")
        print(f"Mezcla por etapa: {output.get('mezcla_por_etapa', {})}")
    print(f"\nPiezas: {int(metrics.get('n_piezas', 0))} (feed {int(metrics.get('n_feed', 0))}, "
          f"historias {int(metrics.get('n_historias', 0))}) · temas cubiertos {metrics.get('pct_temas_cubiertos', 0):.0%} · "
          f"piezas del negocio {metrics.get('pct_piezas_brief', 0):.0%} · búsquedas RAG {int(metrics.get('n_rag_calls', 0))} · "
          f"esquema {'ok' if metrics.get('schema_valid') else 'con errores'} · {metrics.get('latency_s', 0)} s")
    for e in errors:
        print(f"  ! {e}")
    print(f"Resultados en {run_dir}")


# ---------------------------------------------------------------------------
# Approval point 2 (requires_confirmation pattern): Dani reviews the grid in the Sheet.
# ---------------------------------------------------------------------------
SHEET_TO_JSON_STATE = {"Aprobado": "aprobado", "Descartado": "descartado", "Cambios": "pendiente_aprobacion",
                       "Pendiente": "pendiente_aprobacion"}


def to_sheet(pieces: list[dict], tab: str, replace: bool) -> str:
    import parrilla_sheet

    ordered = sorted(pieces, key=lambda p: (str(p.get("fecha_sugerida", "")), str(p.get("id", ""))))
    return parrilla_sheet.write_parrilla(tab, ordered, replace=replace)


def choose_tab(month: str, requested: str | None) -> tuple[str, bool]:
    """Tab name and whether it may overwrite an existing one (asks first)."""
    import gspread
    import parrilla_sheet

    tab = requested or month
    try:
        parrilla_sheet.open_spreadsheet().worksheet(tab)
    except gspread.exceptions.WorksheetNotFound:
        return tab, False
    answer = input(f"\nLa pestaña '{tab}' ya existe en la hoja. ¿Sobrescribirla? (s/n): ").strip().lower()
    if answer.startswith("s"):
        return tab, True
    return f"{tab} ({datetime.now().strftime('%d-%m %H%M')})", False


def revision_message(pieces: list[dict], changes: list[dict]) -> str:
    lines = [f"- {c['id']}: {c['comentario'] or '(sin comentario: mejórala con tu criterio)'}" for c in changes]
    return (
        "Daniela revisó tu parrilla. Rehaz SOLO estas piezas según su comentario, conservando el mismo id, "
        "y respeta tu PROCESO y tus RESTRICCIONES:\n" + "\n".join(lines) +
        "\n\nLas demás piezas no cambian. Esta es la parrilla actual:\n```json\n" +
        json.dumps({"piezas": pieces}, ensure_ascii=False, indent=2) +
        "\n```\nEntrega el JSON completo en el formato indicado, con las piezas corregidas."
    )


def merge_revision(current: list[dict], revised: dict | None, change_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Takes from the revision only the pieces Dani asked to change; everything else stays."""
    new_by_id = {p.get("id"): p for p in (revised or {}).get("piezas", []) if isinstance(p, dict)}
    merged, missing = [], []
    for piece in current:
        if piece.get("id") in change_ids:
            if piece.get("id") in new_by_id:
                fresh = dict(new_by_id[piece["id"]])
                fresh["estado"] = "pendiente_aprobacion"
                fresh["comentarios_dani"] = piece.get("comentarios_dani", "")
                merged.append(fresh)
                continue
            missing.append(piece.get("id"))
        merged.append(piece)
    return merged, missing


def approval_loop(output: dict, inputs: dict, args, run_dir: Path, loop) -> dict:
    import parrilla_sheet as ps

    pieces = [dict(p) for p in output["piezas"] if isinstance(p, dict)]
    tab, replace = choose_tab(inputs["mes"], args.sheet_tab)
    url = to_sheet(pieces, tab, replace)
    history, ronda = [], 1
    instruction = estratega_inputs.fill_prompt(estratega.prompt_path(args.prompt_version).read_text(encoding="utf-8"), inputs)

    while True:
        print(f"\n=== Parrilla en Google Sheets (ronda {ronda}) — esperando a Dani ===\n  {url}")
        print("  Dani marca el Estado de cada pieza (Aprobado / Cambios / Descartado) y escribe en "
              "'Comentarios de Dani' qué cambiar.")
        answer = input("\nCuando termine, presiona Enter (o escribe 'salir' para terminar sin aprobar): ").strip().lower()
        if answer == "salir":
            history.append({"ronda": ronda, "accion": "salir"})
            return {"status": "cancelado", "tab": tab, "url": url, "historial": history, "piezas": pieces}

        decisions = {d["id"]: d for d in ps.read_decisions(tab)}
        summary = ps.summarize_decisions(list(decisions.values()))
        print("  " + " · ".join(f"{s}: {summary[s]}" for s in ps.STATUS_OPTIONS))
        for piece in pieces:
            d = decisions.get(piece.get("id"))
            if d:
                piece["estado"] = SHEET_TO_JSON_STATE.get(d["estado"], "pendiente_aprobacion")
                piece["comentarios_dani"] = d["comentario"]
                piece["_aprobado_por_dani"] = d["estado"] == ps.STATUS_APPROVED
        changes = [{"id": i, "comentario": d["comentario"]} for i, d in decisions.items() if d["estado"] == ps.STATUS_CHANGES]
        history.append({"ronda": ronda, "decisiones": {i: d["estado"] for i, d in decisions.items()},
                        "cambios": changes})

        if summary["listo"]:
            return {"status": "aprobado", "tab": tab, "url": url, "historial": history, "piezas": pieces}
        if not changes:
            print(f"  Aún hay {summary[ps.STATUS_PENDING]} piezas en Pendiente. Pídele a Dani que las revise.")
            continue
        if ronda >= MAX_ROUNDS:
            print(f"\nSe alcanzó el máximo de {MAX_ROUNDS} rondas con piezas en Cambios.")
            return {"status": "incompleto", "tab": tab, "url": url, "historial": history, "piezas": pieces}

        ronda += 1
        print(f"\nRehaciendo {len(changes)} piezas con los comentarios de Dani (ronda {ronda})...")
        result = loop.run_until_complete(run_agent(instruction, revision_message(pieces, changes), args.temperature))
        revised, errors, metrics = evaluate(result, inputs)
        pieces, missing = merge_revision(pieces, revised, {c["id"] for c in changes})
        round_dir = run_dir / f"ronda_{ronda}"
        save_run(round_dir, result, revised, errors, metrics)
        append_error_log(ERROR_LOG, {"origen": "revision", "carpeta": str(round_dir.relative_to(HERE)),
                                     "prompt_version": args.prompt_version, "modelo": estratega.model_id(),
                                     "brief": Path(args.brief).name}, errors)
        if missing:
            print(f"  ! El modelo no regresó estas piezas; se quedan como estaban: {missing}")
        url = to_sheet(pieces, tab, replace=True)


def save_parrilla(run_dir: Path, approval: dict, output: dict) -> dict:
    approved = [{k: v for k, v in p.items() if not k.startswith("_")} for p in approval["piezas"]
                if p.get("estado") == "aprobado"]
    parrilla = {
        "status": approval["status"],
        "mes": output.get("mes"),
        "objetivo_del_mes": output.get("objetivo_del_mes"),
        "estrategia_del_mes": output.get("estrategia_del_mes"),
        "hoja": {"pestana": approval.get("tab"), "url": approval.get("url")},
        "piezas": sorted(approved, key=lambda p: str(p.get("fecha_sugerida", ""))) if approval["status"] == "aprobado" else [],
        "descartadas": [p.get("id") for p in approval["piezas"] if p.get("estado") == "descartado"],
        "historial": approval["historial"],
    }
    (run_dir / "parrilla.json").write_text(json.dumps(parrilla, ensure_ascii=False, indent=2), encoding="utf-8")
    if approval["status"] == "aprobado":
        print(f"\nAprobado: {len(parrilla['piezas'])} piezas → {run_dir / 'parrilla.json'}")
        print("Estas son las piezas que recibirá el Copywriter.")
    else:
        print(f"\nLa parrilla quedó '{approval['status']}': el ciclo no avanza al Copywriter.")
    return parrilla


def log_to_mlflow(args, run_id: str, run_dir: Path, inputs: dict, metrics: dict) -> None:
    import mlflow

    mlruns = PROJECT_ROOT / "mlruns"
    mlruns.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{mlruns / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT)
    experiment_id = (experiment.experiment_id if experiment else
                     mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=(mlruns / "artifacts").as_uri()))
    rag_info = {}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "rag"))
        import retriever

        rag_info = retriever.index_info()
    except Exception:  # the run still logs even if the RAG is not reachable here
        pass
    standards_hash = hashlib.sha1(inputs["estandares_instagram"].encode()).hexdigest()[:12]
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"estratega-{args.prompt_version}-{estratega.model_id()}-{run_id}"):
        mlflow.log_params({
            "agent": "estratega", "prompt_version": args.prompt_version, "model": estratega.model_id(),
            "model_retry_attempts": estratega.retry_attempts(), "tools_version": tools.TOOLS_VERSION,
            "temperature": "default" if args.temperature is None else args.temperature,
            "brief": Path(args.brief).name, "seleccion": str(args.seleccion), "n_temas": len(inputs["temas_aprobados"]),
            "prioridad_principal": inputs["prioridad_principal"], "standards_hash": standards_hash,
            "rag_content_hash": rag_info.get("content_hash", "n/a"), "rag_embedding_model": rag_info.get("embedding_model", "n/a"),
        })
        mlflow.set_tags({"fase": "fase-2", "tipo": "corrida", "adk_version": adk_version.__version__})
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(estratega.prompt_path(args.prompt_version)), "inputs")
        mlflow.log_artifacts(str(run_dir), "outputs")
        (run_dir / "mlflow_run.json").write_text(json.dumps({"run_id": mlflow.active_run().info.run_id}), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Corre el Estratega y lo registra en MLflow.")
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--seleccion", type=Path, required=True, help="seleccion.json del Investigador")
    parser.add_argument("--prompt-version", default="v5")
    parser.add_argument("--model-id", default=None, help="modelo de Gemini (default gemini-3.5-flash-lite)")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--sheet-tab", default=None)
    parser.add_argument("--sin-aprobacion", action="store_true")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--desde-corrida", type=Path, default=None,
                        help="carpeta de una corrida ya hecha: manda su parrilla a la hoja sin llamar al modelo")
    args = parser.parse_args()

    if args.model_id:
        os.environ["ESTRATEGA_MODEL_ID"] = args.model_id
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("Falta GOOGLE_API_KEY (en agents/investigador/.env o agents/estratega/.env).")
    for path in (args.brief, args.seleccion, estratega.prompt_path(args.prompt_version)):
        if not Path(path).exists():
            sys.exit(f"No existe: {path}")

    inputs = estratega_inputs.build_inputs(args.brief.read_text(encoding="utf-8"), args.seleccion)
    instruction = estratega_inputs.fill_prompt(estratega.prompt_path(args.prompt_version).read_text(encoding="utf-8"), inputs)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    run_dir = HERE / "runs" / run_id
    if args.desde_corrida:
        if not (args.desde_corrida / "output.json").exists():
            sys.exit(f"No hay output.json en {args.desde_corrida}")
        run_id, run_dir = args.desde_corrida.name, args.desde_corrida
        args.no_mlflow = True  # that run is already in MLflow
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs.json").write_text(json.dumps(
        {k: v for k, v in inputs.items() if k != "estandares_instagram"}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== Estratega {args.prompt_version} · modelo {estratega.model_id()} · mes {inputs['mes']} · "
          f"{len(inputs['temas_aprobados'])} temas aprobados · prioridad: {inputs['prioridad_principal']} ===")
    print(f"    reintentos ante 429/503: {estratega.retry_attempts()} intentos por llamada")

    loop = asyncio.new_event_loop()
    try:
        if args.desde_corrida:
            # Reuse an existing grid: no model call, the approval happens in the same run folder.
            run_dir = args.desde_corrida if args.desde_corrida.is_absolute() else Path.cwd() / args.desde_corrida
            output = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
            validation = json.loads((run_dir / "validation.json").read_text(encoding="utf-8"))
            errors, metrics = validation["errors"], validation["metrics"]
            print(f"Usando la parrilla ya generada en {run_dir} (sin llamar al modelo).")
            print_summary(output, errors, metrics, run_dir)
        else:
            result = loop.run_until_complete(run_agent(instruction, TRIGGER, args.temperature))
            output, errors, metrics = evaluate(result, inputs)
            save_run(run_dir, result, output, errors, metrics)
            append_error_log(ERROR_LOG, {"origen": "run", "carpeta": str(run_dir.relative_to(HERE)),
                                         "prompt_version": args.prompt_version, "modelo": estratega.model_id(),
                                         "brief": args.brief.name}, errors)
            print_summary(output, errors, metrics, run_dir)

        if not args.sin_aprobacion and output and output.get("piezas"):
            approval = approval_loop(output, inputs, args, run_dir, loop)
            parrilla = save_parrilla(run_dir, approval, output)
            metrics.update({"aprobado": 1.0 if parrilla["status"] == "aprobado" else 0.0,
                            "n_rondas": float(len(approval["historial"])),
                            "n_piezas_aprobadas": float(len(parrilla["piezas"])),
                            "n_piezas_descartadas": float(len(parrilla["descartadas"]))})
    finally:
        # Let the HTTP clients finish closing before the loop goes away
        # (otherwise Python prints "Task was destroyed but it is pending").
        loop.run_until_complete(asyncio.sleep(0.25))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

    if not args.no_mlflow:
        log_to_mlflow(args, run_id, run_dir, inputs, metrics)
        print("Corrida registrada en MLflow (experimento 'dopa-estratega').")


if __name__ == "__main__":
    main()
