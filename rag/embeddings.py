"""Embedding backends for the RAG. One variable picks the provider:

  RAG_EMBEDDING_BACKEND=local              sentence-transformers inside Python (default)
  RAG_EMBEDDING_BACKEND=openai_compatible  any server with an OpenAI-style /v1/embeddings
                                           endpoint (LM Studio today, a cloud provider later);
                                           uses RAG_EMBEDDING_BASE_URL and RAG_EMBEDDING_API_KEY

The model is RAG_EMBEDDING_MODEL in both cases. Index and search must use the
same backend and model; the index stores both and the retriever checks them.
"""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache

VALID_BACKENDS = {"local", "openai_compatible"}


def backend() -> str:
    value = os.environ.get("RAG_EMBEDDING_BACKEND", "local").strip().lower()
    if value not in VALID_BACKENDS:
        raise ValueError(f"RAG_EMBEDDING_BACKEND='{value}' is not valid. Options: {sorted(VALID_BACKENDS)}")
    return value


def _prefix(model: str, kind: str) -> str:
    # e5 models were trained with these prefixes; other models do not need them.
    return f"{kind}: " if "e5" in model.lower() else ""


@lru_cache(maxsize=2)
def _local_model(model: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model)


def _openai_compatible(texts: list[str], model: str) -> list[list[float]]:
    base_url = os.environ.get("RAG_EMBEDDING_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    api_key = os.environ.get("RAG_EMBEDDING_API_KEY", "lm-studio")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), 32):
        body = json.dumps({"model": model, "input": texts[start:start + 32]}).encode()
        request = urllib.request.Request(f"{base_url}/embeddings", data=body, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())["data"]
        vectors += [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]
    # Normalize so cosine similarity behaves the same as with the local backend.
    out = []
    for v in vectors:
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / norm for x in v])
    return out


def embed(texts: list[str], model: str, kind: str, show_progress: bool = False) -> list[list[float]]:
    """kind = "passage" for documents, "query" for questions."""
    texts = [_prefix(model, kind) + t for t in texts]
    if backend() == "local":
        vectors = _local_model(model).encode(texts, normalize_embeddings=True, batch_size=16,
                                             show_progress_bar=show_progress)
        return [v.tolist() for v in vectors]
    return _openai_compatible(texts, model)
