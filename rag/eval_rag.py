#!/usr/bin/env python3
"""Evaluates the retriever against rag/eval_set.json (Fase 4: precision@k, recall@k, MRR).

Usage (from agents_dopa_final_project/, after build_index.py):
  python rag/eval_rag.py              # each question filtered by its agent's tags (as the agents search)
  python rag/eval_rag.py --no-filter  # whole knowledge base, no tag filter
  python rag/eval_rag.py -k 3
  python rag/eval_rag.py --retriever v02   # compare retriever versions

Metrics per question (k = number of chunks returned):
  hit@k       1 if at least one relevant chunk is in the top k
  recall@k    share of the relevant chunks that made it into the top k
  precision@k share of the top k that is relevant
  MRR         1 / rank of the first relevant chunk (0 if none)
Results go to rag/evals/<date>/results.json and to MLflow (experiment "dopa-rag").
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import ingest  # noqa: E402
import retriever  # noqa: E402

EVAL_SET = HERE / "eval_set.json"


def is_relevant(route: str, patterns: list[str]) -> bool:
    for p in patterns:
        if p.startswith("="):
            if route == p[1:]:
                return True
        elif p in route:
            return True
    return False


def main() -> None:
    import mlflow

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument("--no-filter", action="store_true")
    parser.add_argument("--retriever", choices=config.RETRIEVER_VERSIONS, default=config.RETRIEVER_VERSION)
    args = parser.parse_args()

    eval_set = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    chunk_routes = [json.loads(l)["text"].split("\n", 1)[0]
                    for l in ingest.CHUNKS_FILE.read_text(encoding="utf-8").splitlines()]
    try:
        info = retriever.index_info()
    except retriever.IndexNotReady as exc:
        sys.exit(str(exc))

    rows = []
    for q in eval_set["questions"]:
        relevant_routes = [r for r in chunk_routes if is_relevant(r, q["relevant"])]
        if not relevant_routes:
            sys.exit(f"La pregunta {q['id']} no tiene ningún fragmento relevante en el índice: revisa 'relevant'.")
        tags = None if args.no_filter else config.AGENT_TAGS[q["agent"]]
        hits = retriever.search(q["question"], args.k, tags, args.retriever)
        flags = [is_relevant(h["route"], q["relevant"]) for h in hits]
        first = next((i for i, f in enumerate(flags, start=1) if f), None)
        rows.append({
            "id": q["id"], "agent": q["agent"], "question": q["question"],
            "hit": 1.0 if first else 0.0,
            "recall": len({h["route"] for h, f in zip(hits, flags) if f}) / len(relevant_routes),
            "precision": sum(flags) / args.k,
            "mrr": 1.0 / first if first else 0.0,
            "rank_first_relevant": first,
            "retrieved": [{"route": h["route"], "score": h["score"], "relevant": f} for h, f in zip(hits, flags)],
        })

    def agg(subset: list[dict]) -> dict[str, float]:
        return {f"{m}_at_{args.k}" if m != "mrr" else "mrr": statistics.mean(r[m] for r in subset)
                for m in ("hit", "recall", "precision", "mrr")}

    summary = agg(rows)
    by_agent = {a: agg([r for r in rows if r["agent"] == a]) for a in sorted({r["agent"] for r in rows})}

    mode = "sin filtro" if args.no_filter else "filtrado por agente"
    print(f"=== Eval RAG {args.retriever} · {len(rows)} preguntas · k={args.k} · {mode} · {config.EMBEDDING_MODEL} ===")
    for name, metrics in [("TOTAL", summary)] + list(by_agent.items()):
        print(f"  {name:<11}" + " · ".join(f"{m} {v:.2f}" for m, v in metrics.items()))
    misses = [r for r in rows if not r["hit"]]
    late = [r for r in rows if r["hit"] and r["rank_first_relevant"] > 1]
    for title, group in (("No encontradas", misses), ("Encontradas, pero no en primer lugar", late)):
        if group:
            print(f"\n{title}:")
            for r in group:
                print(f"  {r['id']} {r['question']}")
                for h in r["retrieved"]:
                    print(f"      {'✓' if h['relevant'] else ' '} [{h['score']:.3f}] {h['route']}")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = HERE / "evals" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    config_used = {"embedding_model": config.EMBEDDING_MODEL, "embedding_backend": info.get("embedding_backend"), "retriever_version": args.retriever,
                   "chunker_version": info.get("chunker_version"), "content_hash": info.get("content_hash"),
                   "eval_set_version": eval_set["version"], "k": args.k, "tag_filter": not args.no_filter,
                   "n_questions": len(rows)}
    (out_dir / "results.json").write_text(json.dumps({"config": config_used, "summary": summary, "by_agent": by_agent,
                                                      "questions": rows}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    experiment_id = config.setup_mlflow()
    with mlflow.start_run(experiment_id=experiment_id,
                          run_name=f"eval-{args.retriever}-k{args.k}-{'nofilter' if args.no_filter else 'filter'}-{run_id}"):
        mlflow.set_tags({"tipo": "eval", "fase": "fase-3"})
        mlflow.log_params(config_used)
        mlflow.log_metrics(summary)
        for agent, metrics in by_agent.items():
            mlflow.log_metrics({f"{agent}_{m}": v for m, v in metrics.items()})
        mlflow.log_artifact(str(out_dir / "results.json"))
    print(f"\nResultados en {out_dir} y en MLflow (experimento 'dopa-rag').")


if __name__ == "__main__":
    main()
