"""Configuración de MLflow compartida (Clase 4, Bloque C · MLflow).

Todo queda local en agents_dopa_final_project/mlruns/:
  - mlruns/mlflow.db   -> base SQLite con experiments, runs, params y metrics
  - mlruns/artifacts/  -> archivos de cada corrida (prompt, brief, salida, traza)

Para ver la UI (desde agents_dopa_final_project/):
  mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db --port 5001
"""

from __future__ import annotations

from pathlib import Path

import mlflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MLRUNS_DIR = PROJECT_ROOT / "mlruns"
EXPERIMENT_NAME = "dopa-investigador"


def setup_mlflow() -> str:
    """Apunta MLflow a la carpeta local y regresa el experiment_id del Investigador."""
    MLRUNS_DIR.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{MLRUNS_DIR / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        return mlflow.create_experiment(
            EXPERIMENT_NAME, artifact_location=(MLRUNS_DIR / "artifacts").as_uri()
        )
    return experiment.experiment_id
