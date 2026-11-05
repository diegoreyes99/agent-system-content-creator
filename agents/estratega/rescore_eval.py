#!/usr/bin/env python3
"""Re-scores an Estratega eval that already ran, without calling the model.

Reads each case's raw.txt again with the current validation code (for example,
after adding the JSON repair) and rewrites output.json, validation.json and
summary.json. The new summary is logged to the same MLflow parent run, with the
tag "rescored" = date. The model's answers do not change: only how they are read.

Usage (from agents_dopa_final_project/):
  python agents/estratega/rescore_eval.py agents/estratega/evals/<fecha>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_estratega as single  # noqa: E402
from eval_estratega import summarize  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()

    summary_file = args.folder / "summary.json"
    data = json.loads(summary_file.read_text(encoding="utf-8"))
    rows = []
    for old in data["runs"]:
        case_dir = args.folder / f"{old['case']}_r{old['rep']}"
        inputs = json.loads((case_dir / "inputs.json").read_text(encoding="utf-8"))
        inputs.setdefault("prompt_version", data["config"]["prompt_version"])
        trace = json.loads((case_dir / "trace.json").read_text(encoding="utf-8"))
        result = {"raw": (case_dir / "raw.txt").read_text(encoding="utf-8"), **trace}
        result["thinking_tokens"] = result.get("thinking_tokens") or 0
        output, errors, metrics = single.evaluate(result, inputs)
        metrics["run_failed"] = old.get("run_failed", 0.0)
        single.save_run(case_dir, result, output, errors, metrics)
        rows.append({"case": old["case"], "rep": old["rep"], **metrics})
        print(f"  {case_dir.name:<22} {'reparado ' if metrics.get('json_reparado') else ''}"
              f"{int(metrics.get('n_piezas', 0))} piezas · forma {int(metrics.get('n_errores_forma', 0))} · "
              f"contenido {int(metrics.get('n_errores_contenido', 0))}")

    summary = summarize(rows)
    data.update({"summary": summary, "runs": rows, "rescored": datetime.now().isoformat(timespec="minutes")})
    summary_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nuseful_run_rate {summary['useful_run_rate']:.0%} · useful_content_rate {summary['useful_content_rate']:.0%} · "
          f"JSON reparados {sum(r.get('json_reparado', 0) for r in rows):.0f}")

    run_file = args.folder / "mlflow_run.json"
    if run_file.exists():
        import mlflow

        mlflow.set_tracking_uri(f"sqlite:///{single.PROJECT_ROOT / 'mlruns' / 'mlflow.db'}")
        client = mlflow.tracking.MlflowClient()
        run_id = json.loads(run_file.read_text(encoding="utf-8"))["run_id"]
        for key, value in summary.items():
            client.log_metric(run_id, key, value)
        client.set_tag(run_id, "rescored", data["rescored"])
        print(f"Resumen actualizado en MLflow (corrida {run_id[:8]}…).")


if __name__ == "__main__":
    main()
