#!/usr/bin/env python3
"""Evaluates one Estratega configuration against the golden set (Fase 4).

Runs every case of eval_cases/cases.json N times, without the Sheet and
without approval, and logs to MLflow the mean and spread of each metric: a
parent run "eval-..." with the summary, and one child run per case and rep.
Files go to agents/estratega/evals/<fecha>/.

Usage (from agents_dopa_final_project/, with the environment active):
  python agents/estratega/eval_estratega.py --reps 2
  python agents/estratega/eval_estratega.py --reps 2 --model-id gemini-3.8-flash
  python agents/estratega/eval_estratega.py --cases op1_base op5_base --reps 1   # quick check

Then rate the grids by hand: python agents/estratega/rate_estratega.py agents/estratega/evals/<fecha>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_estratega as single  # noqa: E402  (loads .env, ADK and the agent)

CASES_FILE = HERE / "eval_cases" / "cases.json"
SUMMARY_METRICS = [
    "schema_valid", "n_errors", "n_errores_forma", "n_errores_contenido", "n_piezas", "n_feed", "n_historias", "feed_por_semana_mean",
    "feed_por_semana_max", "n_semanas_sin_feed", "pct_temas_cubiertos", "pct_piezas_brief", "pct_piezas_green", "pct_etapa_coherente",
    "desviacion_mezcla", "n_menciones_competidor", "n_rag_calls", "n_calendar_calls",
    "latency_s", "prompt_tokens", "completion_tokens", "thinking_tokens", "costo_usd",
]


async def run_case(case: dict, args) -> tuple[dict, dict | None, list[str], dict, dict]:
    brief_text = (single.PROJECT_ROOT / case["brief"]).read_text(encoding="utf-8")
    inputs = single.estratega_inputs.build_inputs(brief_text, single.PROJECT_ROOT / case["seleccion"])
    inputs["prompt_version"] = args.prompt_version
    template = single.estratega.prompt_path(args.prompt_version).read_text(encoding="utf-8")
    instruction = single.estratega_inputs.fill_prompt(template, inputs)
    try:
        result = await single.run_agent(instruction, single.TRIGGER, args.temperature)
    except Exception as exc:  # quota, network, empty answer...
        error = f"{type(exc).__name__}: {exc}"
        result = {"raw": traceback.format_exc(), "trace": [], "latency_s": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
        return {"run_failed": 1.0, "schema_valid": 0.0}, None, [error], result, inputs
    output, errors, metrics = single.evaluate(result, inputs)
    metrics["run_failed"] = 0.0
    return metrics, output, errors, result, inputs


def summarize(rows: list[dict]) -> dict[str, float]:
    summary = {"n_runs": float(len(rows)),
               "run_failed_rate": statistics.mean(r.get("run_failed", 0.0) for r in rows)}
    # A usable grid: the run did not fail, no validation errors, every approved
    # topic covered and no competitor mentioned.
    summary["useful_run_rate"] = statistics.mean(
        1.0 if (not r.get("run_failed") and r.get("schema_valid") and r.get("pct_temas_cubiertos") == 1.0
                and r.get("n_menciones_competidor", 0) == 0) else 0.0 for r in rows)
    summary["costo_total_usd"] = sum(r.get("costo_usd", 0.0) for r in rows)
    # The proposal is usable even with format errors: JSON readable, no content error, every topic covered.
    summary["useful_content_rate"] = statistics.mean(
        1.0 if (not r.get("run_failed") and r.get("json_parsed") and r.get("n_errores_contenido", 1) == 0
                and r.get("pct_temas_cubiertos") == 1.0) else 0.0 for r in rows)
    for key in SUMMARY_METRICS:
        values = [r[key] for r in rows if not r.get("run_failed") and key in r and r[key] != -1.0]
        if values:
            summary[f"{key}_mean"] = statistics.mean(values)
            summary[f"{key}_std"] = statistics.pstdev(values) if len(values) > 1 else 0.0
            summary[f"{key}_min"], summary[f"{key}_max"] = min(values), max(values)
    return summary


async def run_eval(args, cases: list[dict]) -> None:
    import mlflow

    eval_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    eval_dir = HERE / "evals" / eval_id
    total = len(cases) * args.reps
    config = {
        "agent": "estratega", "prompt_version": args.prompt_version, "model": single.estratega.model_id(),
        "model_retry_attempts": single.estratega.retry_attempts(), "tools_version": single.tools.TOOLS_VERSION,
        "temperature": "default" if args.temperature is None else args.temperature,
        "cases_version": json.loads(CASES_FILE.read_text(encoding="utf-8"))["version"],
        "cases": ",".join(c["case"] for c in cases), "reps": args.reps,
    }
    print(f"=== Eval Estratega {eval_id}: {len(cases)} casos × {args.reps} repeticiones = {total} corridas ===")
    print(f"    prompt {args.prompt_version} · modelo {config['model']} · sin hoja ni aprobación")

    mlruns = single.PROJECT_ROOT / "mlruns"
    mlflow.set_tracking_uri(f"sqlite:///{mlruns / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(single.MLFLOW_EXPERIMENT)
    experiment_id = (experiment.experiment_id if experiment else mlflow.create_experiment(
        single.MLFLOW_EXPERIMENT, artifact_location=(mlruns / "artifacts").as_uri()))

    rows: list[dict] = []
    started = time.perf_counter()
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"eval-{args.prompt_version}-{config['model']}-{eval_id}"):
        mlflow.log_params(config)
        mlflow.set_tags({"fase": "fase-2", "tipo": "eval", "adk_version": single.adk_version.__version__})
        mlflow.log_artifact(str(single.estratega.prompt_path(args.prompt_version)), "inputs")
        mlflow.log_artifact(str(CASES_FILE), "inputs")
        n = 0
        try:
            for case in cases:
                for rep in range(1, args.reps + 1):
                    n += 1
                    name = f"{case['case']}_r{rep}"
                    print(f"\n[{n}/{total}] {name} · {case['nota']}", flush=True)
                    metrics, output, errors, result, inputs = await run_case(case, args)
                    case_dir = eval_dir / name
                    single.save_run(case_dir, result, output, errors, metrics)
                    (case_dir / "inputs.json").write_text(json.dumps(
                        {k: v for k, v in inputs.items() if k not in ("estandares_instagram", "contenidos_green")}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    single.append_error_log(single.ERROR_LOG, {"origen": "eval", "carpeta": str(case_dir.relative_to(HERE)),
                                                               "prompt_version": args.prompt_version,
                                                               "modelo": config["model"], "brief": Path(case["brief"]).name},
                                            errors)
                    with mlflow.start_run(experiment_id=experiment_id, run_name=name, nested=True):
                        mlflow.log_params({**config, "case": case["case"], "brief": Path(case["brief"]).name, "rep": rep})
                        mlflow.log_metrics(metrics)
                        mlflow.log_artifacts(str(case_dir), "outputs")
                    rows.append({"case": case["case"], "rep": rep, **metrics})
                    if metrics.get("run_failed"):
                        print(f"    FALLÓ: {errors[0]}")
                    else:
                        print(f"    {int(metrics['n_piezas'])} piezas (historias {int(metrics.get('n_historias', 0))}) · "
                              f"temas {metrics.get('pct_temas_cubiertos', 0):.0%} · negocio {metrics.get('pct_piezas_brief', 0):.0%} · "
                              f"errores {int(metrics['n_errors'])} · {metrics['latency_s']} s")
                        for e in errors:
                            print(f"    ! {e}")
                    elapsed = time.perf_counter() - started
                    print(f"    llevamos {elapsed / 60:.1f} min · faltan ~{elapsed / n * (total - n) / 60:.0f} min", flush=True)
        except KeyboardInterrupt:
            print(f"\n=== Eval detenido después de {len(rows)} de {total} corridas: se guarda el resumen parcial ===")
            mlflow.set_tag("parcial", "true")

        if rows:
            summary = summarize(rows)
            mlflow.log_metrics(summary)
            eval_dir.mkdir(parents=True, exist_ok=True)
            (eval_dir / "summary.json").write_text(json.dumps({"config": config, "summary": summary, "runs": rows},
                                                              ensure_ascii=False, indent=2), encoding="utf-8")
            mlflow.log_artifact(str(eval_dir / "summary.json"))
            (eval_dir / "mlflow_run.json").write_text(json.dumps({"run_id": mlflow.active_run().info.run_id}),
                                                      encoding="utf-8")

    if not rows:
        return
    print(f"\n=== Resumen ({len(rows)} corridas, {(time.perf_counter() - started) / 60:.1f} min) ===")
    for key in ("useful_run_rate", "useful_content_rate", "run_failed_rate"):
        print(f"  {key:<26}{summary[key]:.0%}")
    for key in ("n_errores_forma", "n_errores_contenido", "n_piezas", "n_historias", "feed_por_semana_mean", "pct_temas_cubiertos", "pct_piezas_brief",
                "pct_etapa_coherente", "desviacion_mezcla", "n_rag_calls", "latency_s"):
        if f"{key}_mean" in summary:
            print(f"  {key:<26}promedio {summary[f'{key}_mean']:.2f} · desv {summary[f'{key}_std']:.2f} · "
                  f"rango {summary[f'{key}_min']:.2f}–{summary[f'{key}_max']:.2f}")
    print(f"\n  Costo del eval: {single.pricing.describe(summary['costo_total_usd'])} "
          f"(promedio por corrida {single.pricing.describe(summary.get('costo_usd_mean'))})")
    print(f"\nArchivos en {eval_dir}\nCalifica con: python agents/estratega/rate_estratega.py {eval_dir.relative_to(single.PROJECT_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el Estratega contra el golden set.")
    parser.add_argument("--prompt-version", default="v6")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--cases", nargs="+", default=None, help="solo estos casos (ids de cases.json)")
    args = parser.parse_args()

    if args.model_id:
        os.environ["ESTRATEGA_MODEL_ID"] = args.model_id
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("Falta GOOGLE_API_KEY.")
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    if args.cases:
        unknown = set(args.cases) - {c["case"] for c in cases}
        if unknown:
            sys.exit(f"Casos desconocidos: {sorted(unknown)}")
        cases = [c for c in cases if c["case"] in args.cases]
    asyncio.run(run_eval(args, cases))


if __name__ == "__main__":
    main()
