#!/usr/bin/env python3
"""Evalúa una configuración del Investigador contra el golden set (Fase 4 / Clase 4, Bloque D).

Corre el agente sobre varios briefs fijos, N veces cada uno, y registra en
MLflow el promedio y la variación de cada métrica. Así una conclusión no sale
de una sola corrida con suerte, sino de qué tan bien y qué tan estable se
comporta la configuración.

Uso (desde agents_dopa_final_project/, con el entorno activo — source ~/.venvs/dopa/bin/activate — y LM Studio corriendo):
  python agents/investigador/eval_investigador.py --prompt-version v4 --trigger t2

Opciones útiles:
  --reps 3               repeticiones por brief (default 3)
  --briefs a.md b.md     otros briefs (default: los 5 de noviembre 2026)
  --temperature 0.3      si no se da, se usa la del servidor
  --search-backend stub  prueba rápida sin internet ni créditos de Tavily

En MLflow queda una corrida "padre" con los promedios (eval-...) y, dentro,
una corrida "hija" por cada brief y repetición. Los archivos de cada corrida
quedan en agents/investigador/evals/<fecha>/.
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

# Reutiliza todo de la corrida individual: mismo agente, misma medición.
import run_investigador as single  # noqa: E402  (carga .env y configura LM Studio al importarse)
from output_checks import apply_source_rules, compute_metrics, extract_json, trace_metrics, validate  # noqa: E402

GOLDEN_SET = sorted((single.PROJECT_ROOT / "baseline" / "briefs").glob("brief_2026-11_op*.md"))

# Métricas que se resumen (promedio, desviación, mínimo y máximo) en la corrida padre.
SUMMARY_METRICS = [
    "schema_valid", "n_hallazgos", "n_alta", "n_recomendados", "pct_fuentes_verificadas", "pct_fuentes_url",
    "n_tool_calls", "n_search_errors", "search_pass_rate", "avg_relevance",
    "latency_s", "prompt_tokens", "completion_tokens",
    "n_fuentes_repetidas", "pct_fuentes_aprovechadas", "prioridad_sin_variacion", "n_temas_copia_busqueda",
]


async def run_case(brief: Path, args) -> tuple[dict, dict | None, list[str], dict | None]:
    """Corre un caso. Si falla, regresa métricas en cero en vez de tumbar todo el eval."""
    try:
        result = await single.run_agent(
            brief.read_text(encoding="utf-8"), args.prompt_version, args.temperature,
            single.TRIGGERS[args.trigger],
        )
    except Exception as exc:  # LM Studio caído, timeout, etc.
        error = f"{type(exc).__name__}: {exc}"
        metrics = compute_metrics(None, [error])
        metrics.update({"run_failed": 1.0, "latency_s": 0.0})
        return metrics, None, [error], {"raw": traceback.format_exc(), "trace": [], "latency_s": 0.0,
                                         "prompt_tokens": 0, "completion_tokens": 0, "correcciones": []}

    try:
        output = extract_json(result["raw"])
        errors = validate(output, args.prompt_version)
    except (ValueError, json.JSONDecodeError) as exc:
        output, errors = None, [f"JSON no parseable: {exc}"]

    result["correcciones"] = apply_source_rules(output, result["trace"], args.prompt_version)
    metrics = compute_metrics(output, errors)
    metrics.update(trace_metrics(output, result["trace"]))
    metrics.update({
        "n_recomendados_corregidos": float(len(result["correcciones"])),
        "run_failed": 0.0,
        "latency_s": round(result["latency_s"], 2),
        "prompt_tokens": float(result["prompt_tokens"]),
        "completion_tokens": float(result["completion_tokens"]),
    })
    return metrics, output, errors, result


def summarize(rows: list[dict]) -> dict[str, float]:
    summary: dict[str, float] = {"n_runs": float(len(rows))}
    summary["run_failed_rate"] = statistics.mean(r.get("run_failed", 0.0) for r in rows)
    # Corrida "útil": no falló, esquema válido y al menos un hallazgo con fuente verificada.
    summary["useful_run_rate"] = statistics.mean(
        1.0 if (r.get("schema_valid") and r.get("n_hallazgos", 0) > 0 and r.get("pct_fuentes_verificadas", 0) > 0) else 0.0
        for r in rows
    )
    for key in SUMMARY_METRICS:
        values = [r.get(key, 0.0) for r in rows if not r.get("run_failed")]
        if key == "pct_fuentes_verificadas":
            # Solo tiene sentido en corridas con hallazgos: con 0 hallazgos no hay fuentes que verificar.
            values = [r[key] for r in rows if not r.get("run_failed") and r.get("n_hallazgos", 0) > 0]
        if not values:
            continue
        summary[f"{key}_mean"] = statistics.mean(values)
        summary[f"{key}_std"] = statistics.pstdev(values) if len(values) > 1 else 0.0
        summary[f"{key}_min"] = min(values)
        summary[f"{key}_max"] = max(values)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el Investigador contra el golden set.")
    parser.add_argument("--prompt-version", default="v4")
    parser.add_argument("--trigger", choices=sorted(single.TRIGGERS), default="t2")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--briefs", type=Path, nargs="+", default=GOLDEN_SET)
    parser.add_argument("--model", choices=sorted(single.investigador.VALID_PROVIDERS), default=None,
                        help="gemini (Gemini API, default, needs GOOGLE_API_KEY) or local (LM Studio)")
    parser.add_argument("--search-backend", choices=sorted(single.tools.VALID_BACKENDS), default=None)
    args = parser.parse_args()

    if args.model:
        os.environ["MODEL_PROVIDER"] = args.model
    if single.investigador.provider() == "gemini" and not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("Missing GOOGLE_API_KEY. Add it to agents/investigador/.env (get one at https://aistudio.google.com).")
    if args.search_backend:
        os.environ["SEARCH_BACKEND"] = args.search_backend
    if single.tools.get_backend() == "tavily" and not os.environ.get("TAVILY_API_KEY"):
        sys.exit("Falta TAVILY_API_KEY en agents/investigador/.env (o usa --search-backend stub).")
    missing = [b for b in args.briefs if not b.exists()]
    if missing or not args.briefs:
        sys.exit(f"No se encontraron los briefs: {missing or 'golden set vacío'}")
    if not single.investigador.prompt_path(args.prompt_version).exists():
        sys.exit(f"No existe el prompt: {single.investigador.prompt_path(args.prompt_version)}")

    # Todas las corridas en un solo ciclo asíncrono: LiteLLM reutiliza su
    # conexión y no se rompe entre corridas ("Event loop is closed").
    try:
        asyncio.run(run_eval(args))
    except KeyboardInterrupt:
        pass  # el resumen parcial ya se guardó dentro de run_eval


async def run_eval(args) -> None:
    import mlflow

    from tracking import setup_mlflow

    eval_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    eval_dir = HERE / "evals" / eval_id
    total = len(args.briefs) * args.reps
    config = {
        "agent": "investigador",
        "prompt_version": args.prompt_version,
        "trigger_version": args.trigger,
        "model": single.investigador.model_id(),
        "model_provider": single.investigador.provider(),
        "model_retry_attempts": single.investigador.retry_attempts(),
        "temperature": "default" if args.temperature is None else args.temperature,
        "search_backend": single.tools.get_backend(),
        "tools_version": single.tools.TOOLS_VERSION,
        "search_min_score": single.tools.get_min_score(),
        "max_search_calls": single.investigador.MAX_SEARCH_CALLS,
        "max_llm_calls": single.MAX_LLM_CALLS,
        "golden_set": ",".join(b.name for b in args.briefs),
        "reps": args.reps,
    }
    print(f"=== Eval {eval_id}: {len(args.briefs)} briefs × {args.reps} repeticiones = {total} corridas ===")
    print(f"    prompt {args.prompt_version} · trigger {args.trigger} · modelo {config['model']} · búsqueda {config['search_backend']}")
    if config["model_provider"] == "gemini":
        print(f"    reintentos ante 429/503: {config['model_retry_attempts']} intentos por llamada"
              + ("" if single.investigador.retries_supported() else " (NO disponibles en esta versión de ADK)"))

    experiment_id = setup_mlflow()
    rows: list[dict] = []
    started = time.perf_counter()
    with mlflow.start_run(experiment_id=experiment_id,
                          run_name=f"eval-{args.prompt_version}-{args.trigger}-{config['search_backend']}-{eval_id}") as parent:
        single.save_mlflow_run_id(eval_dir, parent)
        mlflow.log_params(config)
        mlflow.set_tags({"fase": "fase-2", "tipo": "eval", "adk_version": single.adk_version.__version__})
        mlflow.log_artifact(str(single.investigador.prompt_path(args.prompt_version)), "inputs")

        n = 0
        interrupted = False
        all_corrections: list[dict] = []
        try:
            for brief in args.briefs:
                for rep in range(1, args.reps + 1):
                    n += 1
                    case = f"{brief.stem}_r{rep}"
                    print(f"\n[{n}/{total}] {case} ...", flush=True)
                    metrics, output, errors, result = await run_case(brief, args)
                    case_dir = eval_dir / case
                    single.save_run(case_dir, result, output, errors, metrics)
                    single.append_error_log(single.ERROR_LOG, {
                        "origen": "eval", "carpeta": str(case_dir.relative_to(HERE)),
                        "prompt_version": args.prompt_version, "modelo": config["model"], "brief": brief.name,
                    }, errors, result["correcciones"])
                    all_corrections += [{"case": case, **c} for c in result["correcciones"]]

                    with mlflow.start_run(experiment_id=experiment_id, run_name=case, nested=True) as child:
                        single.save_mlflow_run_id(case_dir, child)
                        mlflow.log_params({**config, "brief": brief.name, "rep": rep})
                        mlflow.log_metrics(metrics)
                        mlflow.log_artifacts(str(case_dir), "outputs")

                    rows.append({"case": case, "brief": brief.name, "rep": rep, **metrics})
                    status = "FALLÓ" if metrics.get("run_failed") else (
                        f"{int(metrics['n_hallazgos'])} hallazgos · {int(metrics.get('n_tool_calls', 0))} búsquedas · "
                        f"fuentes verificadas {metrics.get('pct_fuentes_verificadas', 0):.0%} · "
                        f"esquema {'ok' if metrics['schema_valid'] else 'inválido'} · {metrics['latency_s']} s")
                    print(f"    {status}")
                    single.print_errors(errors, result["correcciones"], indent="    ")
                    elapsed = time.perf_counter() - started
                    remaining = elapsed / n * (total - n)
                    print(f"    llevamos {elapsed / 60:.1f} min · faltan ~{remaining / 60:.0f} min", flush=True)
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Ctrl+C: no se pierde lo que ya corrió; se resume con las corridas terminadas.
            interrupted = True
            print(f"\n=== Eval detenido después de {len(rows)} de {total} corridas ===", flush=True)
        mlflow.set_tag("interrupted", str(interrupted).lower())
        if not rows:
            return

        summary = summarize(rows)
        mlflow.log_metrics(summary)
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "summary.json").write_text(
            json.dumps({"config": config, "summary": summary, "runs": rows, "correcciones": all_corrections},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        mlflow.log_artifact(str(eval_dir / "summary.json"))

    print(f"\n=== Resumen ({len(rows)} corridas, {(time.perf_counter() - started) / 60:.1f} min) ===")
    for key in ("useful_run_rate", "run_failed_rate"):
        print(f"  {key:<28}{summary[key]:.0%}")
    for key in ("schema_valid", "n_hallazgos", "pct_fuentes_verificadas", "n_tool_calls",
                "search_pass_rate", "avg_relevance", "latency_s"):
        if f"{key}_mean" in summary:
            print(f"  {key:<28}promedio {summary[f'{key}_mean']:.2f} · desv {summary[f'{key}_std']:.2f} · "
                  f"rango {summary[f'{key}_min']:.2f}–{summary[f'{key}_max']:.2f}")
    print(f"\nArchivos en {eval_dir}")
    print("En MLflow: experimento 'dopa-investigador', corrida padre 'eval-...'.")


if __name__ == "__main__":
    main()
