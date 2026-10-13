#!/usr/bin/env python3
"""Paso 9: pone lado a lado el Investigador del baseline (Fase 1) y una corrida del agente nuevo.

Ambos se miden con las mismas reglas (output_checks.py). Con --log-baseline
además registra el baseline en MLflow como su propia corrida
("E00-baseline-sin-herramientas"), así la comparación también se ve en la UI.

Uso (desde agents_dopa_final_project/):
  python agents/investigador/compare_with_baseline.py \
      --baseline baseline/cycles/2026-10-13_0019/01_investigador.json \
      --run agents/investigador/runs/<fecha>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from output_checks import compute_metrics, validate  # noqa: E402

ROWS = [
    ("json_parsed", "JSON parseable"),
    ("schema_valid", "Esquema válido"),
    ("n_schema_errors", "Errores de esquema"),
    ("n_hallazgos", "Hallazgos"),
    ("n_alta", "Hallazgos prioridad alta"),
    ("n_tendencias", "Tendencias de formato"),
    ("pct_fuentes_stub", "% fuentes del stub"),
    ("pct_fuentes_url", "% fuentes que son URL"),
    ("n_tool_calls", "Tool calls"),
    ("latency_s", "Latencia (s)"),
]


def measure(output_path: Path) -> tuple[dict, dict]:
    output = json.loads(output_path.read_text(encoding="utf-8"))
    return output, compute_metrics(output, validate(output))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True, help="01_investigador.json del baseline")
    parser.add_argument("--run", type=Path, required=True, help="Carpeta agents/investigador/runs/<fecha>")
    parser.add_argument("--log-baseline", action="store_true", help="Registra el baseline en MLflow (hazlo una sola vez)")
    args = parser.parse_args()

    base_output, base_metrics = measure(args.baseline)
    base_metrics["n_tool_calls"] = 0.0  # el baseline no tenía herramientas

    run_output_path = args.run / "output.json"
    if not run_output_path.exists():
        sys.exit(f"La corrida no tiene output.json (¿el JSON no se pudo parsear?). Revisa {args.run / 'raw.txt'}")
    new_output, new_metrics = measure(run_output_path)
    trace = json.loads((args.run / "trace.json").read_text(encoding="utf-8"))
    new_metrics["n_tool_calls"] = float(sum(1 for t in trace["trace"] if t["type"] == "tool_call"))
    new_metrics["latency_s"] = round(trace["latency_s"], 2)

    print(f"\n{'Métrica':<28}{'Baseline (Fase 1)':>20}{'Agente Fase 2':>18}")
    print("-" * 66)
    for key, label in ROWS:
        b, n = base_metrics.get(key, "—"), new_metrics.get(key, "—")
        print(f"{label:<28}{str(b):>20}{str(n):>18}")

    print("\nResumen ejecutivo — baseline:\n  " + base_output.get("resumen_ejecutivo", "—"))
    print("\nResumen ejecutivo — agente Fase 2:\n  " + new_output.get("resumen_ejecutivo", "—"))
    print("\nTemas — agente Fase 2:")
    for h in new_output.get("hallazgos", []):
        print(f"  [{h.get('prioridad', '?')}] {h.get('tema', '?')}  ← {h.get('fuente', '?')}")

    if args.log_baseline:
        import mlflow

        from tracking import setup_mlflow

        experiment_id = setup_mlflow()
        with mlflow.start_run(experiment_id=experiment_id, run_name="E00-baseline-sin-herramientas"):
            mlflow.log_params({
                "agent": "investigador",
                "prompt_version": "v1",
                "model": "qwen3-4b (baseline Fase 1)",
                "temperature": "default",
                "search_backend": "none",
                "tools": "none",
                "brief": "ciclo-1-brief.md",
            })
            mlflow.set_tag("fase", "fase-1-baseline")
            mlflow.log_metrics({k: v for k, v in base_metrics.items() if k != "latency_s"})
            mlflow.log_artifact(str(args.baseline), "outputs")
        print("\nBaseline registrado en MLflow como 'E00-baseline-sin-herramientas'.")


if __name__ == "__main__":
    main()
