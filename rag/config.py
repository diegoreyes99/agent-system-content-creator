"""Shared settings for the RAG (Fase 3, adelantada al Estratega)."""

from __future__ import annotations

from pathlib import Path

import os

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INDEX_DIR = HERE / "index"

# Local embedding model (decision 2026-10-22): the documents never leave the Mac.
# Changing it requires rebuilding the index (build_index.py) and re-running the eval.
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
COLLECTION = "dopa_knowledge"  # business, audience, voice and visual identity
# Retriever versions (one change per version, measured with eval_rag.py):
#   v01: semantic search only, top-k, optional tag filter
#   v02: hybrid = semantic + BM25 (exact words), fused with Reciprocal Rank Fusion
RETRIEVER_VERSIONS = ("v01", "v02")
RETRIEVER_VERSION = os.environ.get("RAG_RETRIEVER_VERSION", "v01")

# Every tag a chunk can have, and the tags each agent searches by default.
TAGS = ("negocio", "audiencia", "voz", "visual")
AGENT_TAGS = {
    "estratega": ("negocio", "audiencia", "voz"),
    "copywriter": ("voz", "audiencia", "negocio"),
    "disenador": ("visual", "voz", "audiencia"),
}

MLFLOW_EXPERIMENT = "dopa-rag"


def setup_mlflow() -> str:
    import mlflow

    mlruns = PROJECT_ROOT / "mlruns"
    mlruns.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{mlruns / 'mlflow.db'}")
    experiment = mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT)
    if experiment is None:
        return mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=(mlruns / "artifacts").as_uri())
    return experiment.experiment_id
