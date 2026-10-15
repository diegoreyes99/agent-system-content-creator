#!/usr/bin/env python3
"""Califica a mano los temas del Investigador con la rúbrica (rubrica_investigador.md).

Uso (desde agents_dopa_final_project/):
  # una corrida suelta
  python agents/investigador/rate_investigador.py agents/investigador/runs/<fecha>
  # un eval completo: toma una muestra al azar de 10 temas entre todos los casos
  python agents/investigador/rate_investigador.py agents/investigador/evals/<fecha> --sample 10

Por cada tema muestra lo que propuso el Investigador junto al texto real que
regresó la búsqueda para esa URL, y pide las calificaciones. Guarda
ratings.csv en la carpeta y, si la corrida está en MLflow, registra los
promedios como métricas human_* en esa misma corrida.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from pathlib import Path

FIELDS = ["case", "id", "tema", "fuente", "relevancia", "fidelidad", "accionabilidad", "promocion", "nota"]


def load_case(case_dir: Path) -> list[dict]:
    """Regresa los temas de una corrida, cada uno con el texto real de su fuente."""
    output_path, trace_path = case_dir / "output.json", case_dir / "trace.json"
    if not output_path.exists() or not trace_path.exists():
        return []
    output = json.loads(output_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))["trace"]
    snippets = {}
    for t in trace:
        for r in (t.get("response") or {}).get("results", []) or []:
            snippets.setdefault(str(r.get("url", "")).strip(), r)
    items = []
    for h in output.get("hallazgos") or []:
        if isinstance(h, dict):
            source = snippets.get(str(h.get("fuente", "")).strip(), {})
            items.append({"case": case_dir.name, "hallazgo": h, "source": source})
    return items


def ask_score(label: str) -> int:
    while True:
        answer = input(f"  {label} (1-3): ").strip()
        if answer in ("1", "2", "3"):
            return int(answer)
        print("    Escribe 1, 2 o 3.")


def ask_yes_no(label: str) -> bool:
    while True:
        answer = input(f"  {label} (s/n): ").strip().lower()
        if answer in ("s", "si", "sí", "n", "no"):
            return answer.startswith("s")
        print("    Escribe s o n.")


def log_to_mlflow(case_dir: Path, rows: list[dict]) -> None:
    """Registra los promedios en la corrida de MLflow guardada en mlflow_run.json."""
    run_file = case_dir / "mlflow_run.json"
    if not run_file.exists() or not rows:
        return
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mlflow

    from tracking import setup_mlflow

    setup_mlflow()
    run_id = json.loads(run_file.read_text(encoding="utf-8"))["run_id"]
    client = mlflow.tracking.MlflowClient()
    for key in ("relevancia", "fidelidad", "accionabilidad"):
        client.log_metric(run_id, f"human_{key}_mean", statistics.mean(r[key] for r in rows))
    client.log_metric(run_id, "human_promocion_rate", statistics.mean(1.0 if r["promocion"] else 0.0 for r in rows))
    client.log_metric(run_id, "human_n_rated", float(len(rows)))
    print(f"  Registrado en MLflow (corrida {run_id[:8]}…).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Carpeta de una corrida (runs/<fecha>) o de un eval (evals/<fecha>)")
    parser.add_argument("--sample", type=int, default=10, help="Cuántos temas calificar como máximo (default 10)")
    parser.add_argument("--seed", type=int, default=7, help="Semilla de la muestra, para poder repetirla")
    args = parser.parse_args()

    is_eval = (args.folder / "summary.json").exists()
    case_dirs = sorted(d for d in args.folder.iterdir() if d.is_dir()) if is_eval else [args.folder]
    items = [item for d in case_dirs for item in load_case(d)]
    if not items:
        raise SystemExit("No hay temas para calificar en esa carpeta.")
    if len(items) > args.sample:
        items = random.Random(args.seed).sample(items, args.sample)

    print(f"Vas a calificar {len(items)} temas. Rúbrica: agents/investigador/rubrica_investigador.md\n")
    rows = []
    for n, item in enumerate(items, start=1):
        h, src = item["hallazgo"], item["source"]
        print("=" * 78)
        print(f"[{n}/{len(items)}] {item['case']} · tema {h.get('id', '?')}  [{h.get('prioridad', '?')}]"
              f"{'  ★ recomendado' if h.get('recomendado') else ''}")
        print(f"\n  TEMA: {h.get('tema', '')}")
        if h.get("que_dice_la_fuente"):
            print(f"  DICE QUE LA FUENTE DICE: {h['que_dice_la_fuente']}")
        print(f"  PARA DOPA: {h.get('relevancia_dopa', '')}")
        print(f"\n  FUENTE: {h.get('fuente', '')}")
        if src:
            print(f"  TÍTULO REAL: {src.get('title', '')}")
            print(f"  TEXTO REAL DE LA BÚSQUEDA: {src.get('snippet', '')}")
        else:
            print("  (Esta URL no aparece en los resultados de la búsqueda: posible fuente inventada.)")
        print()
        rows.append({
            "case": item["case"], "id": h.get("id", ""), "tema": h.get("tema", ""), "fuente": h.get("fuente", ""),
            "relevancia": ask_score("Relevancia"),
            "fidelidad": ask_score("Fidelidad"),
            "accionabilidad": ask_score("Accionabilidad"),
            "promocion": ask_yes_no("¿Es la promoción de otro negocio?"),
            "nota": input("  Nota (opcional, Enter para saltar): ").strip(),
        })

    out = args.folder / "ratings.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== Resumen ===")
    for key in ("relevancia", "fidelidad", "accionabilidad"):
        print(f"  {key:<16}{statistics.mean(r[key] for r in rows):.2f} / 3")
    print(f"  {'promoción':<16}{sum(r['promocion'] for r in rows)} de {len(rows)}")
    print(f"Guardado en {out}")

    # En un eval, los promedios van a la corrida padre; en una corrida suelta, a esa corrida.
    log_to_mlflow(args.folder, rows)


if __name__ == "__main__":
    main()
