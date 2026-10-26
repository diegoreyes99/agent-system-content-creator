#!/usr/bin/env python3
"""Builds the vector index from DOPA's documents (run it again whenever a document changes).

Usage (from agents_dopa_final_project/, with the venv active):
  python rag/build_index.py

Steps: read and chunk the .docx files (ingest.py) → embed each chunk with the
local model → store everything in ChromaDB (rag/index/, ignored by git). The
first run downloads the model (~1.1 GB) from Hugging Face; later runs reuse it.
Each build is logged to MLflow (experiment "dopa-rag") so every agent run can
be traced back to the knowledge version it used.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import embeddings  # noqa: E402
import ingest  # noqa: E402


def main() -> None:
    import chromadb
    import mlflow

    started = time.perf_counter()
    chunks = ingest.build_chunks()
    ingest.CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ingest.CHUNKS_FILE.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(chunks)} fragmentos de {len(ingest.DOCUMENTS)} documentos.")

    print(f"Embeddings con {config.EMBEDDING_MODEL} (backend {embeddings.backend()}; "
          "con el backend local, la primera vez se descarga el modelo)...")
    vectors = embeddings.embed([c["text"] for c in chunks], config.EMBEDDING_MODEL, "passage", show_progress=True)

    # Rebuild from scratch: the index always matches the current documents exactly.
    if config.INDEX_DIR.exists():
        shutil.rmtree(config.INDEX_DIR)
    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    content_hash = hashlib.sha1("".join(c["text"] for c in chunks).encode()).hexdigest()[:12]
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    collection = client.create_collection(
        name=config.COLLECTION,
        metadata={"hnsw:space": "cosine", "embedding_model": config.EMBEDDING_MODEL,
                  "embedding_backend": embeddings.backend(),
                  "chunker_version": ingest.CHUNKER_VERSION, "content_hash": content_hash, "built_at": built_at},
    )
    collection.add(
        ids=[c["id"] for c in chunks],
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[{k: c[k] for k in ("document", "doc_title", "section", "subsection", "tag", "n_words")}
                   for c in chunks],
    )
    elapsed = time.perf_counter() - started
    print(f"Índice listo en {config.INDEX_DIR} ({elapsed:.0f} s) · versión del contenido {content_hash}")

    experiment_id = config.setup_mlflow()
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"build-{built_at}"):
        mlflow.set_tags({"tipo": "build_index", "fase": "fase-3"})
        mlflow.log_params({"embedding_model": config.EMBEDDING_MODEL, "embedding_backend": embeddings.backend(), "chunker_version": ingest.CHUNKER_VERSION,
                           "content_hash": content_hash, "documents": ",".join(ingest.DOCUMENTS),
                           "max_words": ingest.MAX_WORDS})
        mlflow.log_metrics({"n_chunks": float(len(chunks)), "build_s": round(elapsed, 1)})
    print("Registrado en MLflow (experimento 'dopa-rag').")


if __name__ == "__main__":
    main()
