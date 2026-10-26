"""Searches DOPA's knowledge base. This is what the agents' RAG tool calls.

Usage as a script (quick manual test):
  python rag/retriever.py "¿Qué frena a Ana para inscribirse?" --agent estratega
"""

from __future__ import annotations

import argparse
import sys
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import embeddings  # noqa: E402


class IndexNotReady(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _collection():
    import chromadb

    if not config.INDEX_DIR.exists():
        raise IndexNotReady("No existe el índice: corre primero python rag/build_index.py")
    collection = chromadb.PersistentClient(path=str(config.INDEX_DIR)).get_collection(config.COLLECTION)
    meta = collection.metadata or {}
    built_with = (meta.get("embedding_backend"), meta.get("embedding_model"))
    now = (embeddings.backend(), config.EMBEDDING_MODEL)
    if built_with != now:
        # Searching with a different model than the one used to index returns garbage.
        raise IndexNotReady(f"El índice se construyó con {built_with[1]} ({built_with[0]}) y ahora se busca con "
                            f"{now[1]} ({now[0]}): reconstrúyelo con python rag/build_index.py")
    return collection


def index_info() -> dict:
    return dict(_collection().metadata or {})


def _where(tags) -> dict | None:
    if not tags:
        return None
    unknown = [t for t in tags if t not in config.TAGS]
    if unknown:
        raise ValueError(f"Etiquetas desconocidas: {unknown}. Opciones: {config.TAGS}")
    return {"tag": tags[0]} if len(tags) == 1 else {"tag": {"$in": list(tags)}}


def _semantic(query: str, n: int, tags) -> list[dict]:
    """Chunks ranked by meaning (cosine similarity of embeddings)."""
    embedding = embeddings.embed([query], config.EMBEDDING_MODEL, "query")[0]
    result = _collection().query(query_embeddings=[embedding], n_results=n, where=_where(tags),
                                 include=["documents", "metadatas", "distances"])
    return [{"id": cid, "route": text.split("\n", 1)[0], "text": text, "tag": meta.get("tag"),
             "document": meta.get("document"), "score": round(1 - float(distance), 3)}
            for cid, text, meta, distance in zip(result["ids"][0], result["documents"][0],
                                                 result["metadatas"][0], result["distances"][0])]


# --- v02: BM25 (exact words) -------------------------------------------------
# Small Spanish stopword list: words that appear everywhere and say nothing.
_STOPWORDS = set("""a al algo ante con contra cual cuales cuando de del desde donde durante el ella ellas ellos
en entre era es esa ese eso esta este esto estos estas fue ha hace hay la las le les lo los mas me mi muy
nada ni no nos o otra otro para pero por porque que quien se sea ser si sin sobre su sus tambien tiene
todo tu un una uno unos unas y ya yo como cada cuanto cuanta cuantos cuantas debe hoy""".split())


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))  # "fotografía" = "fotografia"
    words = re.findall(r"[a-z0-9]+", text)
    # Crude plural folding ("fotos" = "foto") so singular and plural match.
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if w not in _STOPWORDS and len(w) > 1]


@lru_cache(maxsize=1)
def _bm25_corpus():
    data = _collection().get(include=["documents", "metadatas"])
    docs = [{"id": cid, "text": text, "meta": meta, "tokens": _tokens(text)}
            for cid, text, meta in zip(data["ids"], data["documents"], data["metadatas"])]
    df = Counter(t for d in docs for t in set(d["tokens"]))
    avg_len = sum(len(d["tokens"]) for d in docs) / max(len(docs), 1)
    return docs, df, avg_len


def _bm25(query: str, n: int, tags, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    """Chunks ranked by shared words with the question (classic BM25)."""
    docs, df, avg_len = _bm25_corpus()
    q_tokens = _tokens(query)
    total = len(docs)
    scored = []
    for d in docs:
        if tags and d["meta"].get("tag") not in tags:
            continue
        tf = Counter(d["tokens"])
        score = 0.0
        for t in q_tokens:
            if t in tf:
                idf = math.log(1 + (total - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d["tokens"]) / avg_len))
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [{"id": d["id"], "route": d["text"].split("\n", 1)[0], "text": d["text"], "tag": d["meta"].get("tag"),
             "document": d["meta"].get("document"), "score": round(s, 3)} for s, d in scored[:n]]


def _rrf(rankings: list[list[dict]], k: int, rrf_k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: each list votes 1/(60 + rank); no need to compare their raw scores."""
    fused: dict[str, float] = {}
    by_id: dict[str, dict] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            fused[hit["id"]] = fused.get(hit["id"], 0.0) + 1.0 / (rrf_k + rank)
            by_id.setdefault(hit["id"], hit)
    best = sorted(fused, key=lambda cid: -fused[cid])[:k]
    return [{**by_id[cid], "score": round(fused[cid], 4)} for cid in best]


def search(query: str, k: int = 4, tags: tuple[str, ...] | list[str] | None = None,
           version: str | None = None) -> list[dict]:
    """Top-k chunks for a question, optionally only from some tags.

    Returns [{"id", "route", "text", "tag", "document", "score"}], best first.
    v01: score = cosine similarity. v02: score = fused RRF score (only the order matters).
    """
    version = version or config.RETRIEVER_VERSION
    if version not in config.RETRIEVER_VERSIONS:
        raise ValueError(f"Versión de buscador desconocida: {version}. Opciones: {config.RETRIEVER_VERSIONS}")
    if version == "v01":
        return _semantic(query, k, tags)
    pool = 20  # candidates from each method before fusing
    return _rrf([_semantic(query, pool, tags), _bm25(query, pool, tags)], k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba manual del buscador.")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument("--agent", choices=sorted(config.AGENT_TAGS), default=None,
                        help="filtra por las etiquetas de ese agente")
    parser.add_argument("--retriever", choices=config.RETRIEVER_VERSIONS, default=None)
    args = parser.parse_args()
    tags = config.AGENT_TAGS[args.agent] if args.agent else None
    try:
        hits = search(args.query, args.k, tags, args.retriever)
    except IndexNotReady as exc:
        sys.exit(str(exc))
    for i, h in enumerate(hits, start=1):
        body = h["text"].split("\n", 1)[1] if "\n" in h["text"] else ""
        print(f"\n{i}. [{h['score']:.3f}] ({h['tag']}) {h['route']}\n   {body[:300]}")


if __name__ == "__main__":
    main()
