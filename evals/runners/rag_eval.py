"""Retrieval evaluation: Recall@5, MRR and nDCG@10 per persona for every RAG variant.

Gold = the project ids the persona cited in the proposal actually sent for that job; a retrieved
chunk is relevant when its project_id is in that set (evidence is graded at project level because
every chunk of a project is legitimate evidence for it).

  uv run python -m evals.runners.rag_eval [--variants v0_naive,v2_hybrid] [--personas ai_ml] [--limit 40]
Writes evals/results/rag_<variant>.json and evals/results/rag_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from typing import Any

from agent.settings import ROOT
from rag.retriever import VARIANTS, Resources, build_retriever

DATASETS = ROOT / "evals/datasets"
RESULTS = ROOT / "evals/results"


def load_dev(persona: str, limit: int | None) -> list[dict[str, Any]]:
    p = DATASETS / f"dev_{persona}.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.open(encoding="utf-8")]
    rows = [r for r in rows if r.get("gold_projects")]
    return rows[:limit] if limit else rows


def metrics(
    ranked_projects: list[str | None], gold: set[str], k_recall: int = 5, k_ndcg: int = 10
) -> dict[str, float]:
    """ranked_projects: project id per retrieved chunk in rank order (duplicates collapse)."""
    seen: list[str] = []
    for p in ranked_projects:
        if p and p not in seen:
            seen.append(p)
    recall = len(set(seen[:k_recall]) & gold) / len(gold) if gold else 0.0
    rr = 0.0
    for i, p in enumerate(seen, 1):
        if p in gold:
            rr = 1.0 / i
            break
    dcg = sum(1.0 / math.log2(i + 1) for i, p in enumerate(seen[:k_ndcg], 1) if p in gold)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k_ndcg) + 1))
    return {"recall@5": recall, "mrr": rr, "ndcg@10": dcg / idcg if idcg else 0.0}


def run_variant(
    name: str,
    personas: list[str],
    limit: int | None,
    res: Resources,
    query_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate metrics per persona; with `query_rows`, also one row per query for analysis."""
    retriever = build_retriever(name, res)
    out: dict[str, Any] = {"variant": name, "personas": {}, "n_jobs": 0}
    all_rows: list[dict[str, float]] = []
    for persona in personas:
        rows = load_dev(persona, limit)
        if not rows:
            continue
        per: list[dict[str, float]] = []
        lat: list[float] = []
        for r in rows:
            t0 = time.perf_counter()
            ev = retriever.retrieve(r["job"], persona, k=12)
            lat.append(time.perf_counter() - t0)
            # leakage guard: the past proposal sent for this very job is in the corpus and would
            # hand over the gold project ids; it is never legitimate evidence for the same job
            ev = [e for e in ev if not (e.doc_type == "proposal" and e.job_id == r["job_id"])][:10]
            m = metrics([e.project_id for e in ev], set(r["gold_projects"]))
            per.append(m)
            if query_rows is not None:
                query_rows.append(
                    {
                        "variant": name,
                        "persona": persona,
                        "job_id": r["job_id"],
                        "title": r["job"].get("title", "")[:90],
                        "gold": sorted(r["gold_projects"]),
                        "ranked": [
                            {
                                "project": e.project_id,
                                "doc_type": e.doc_type,
                                "score": round(e.score, 4),
                            }
                            for e in ev
                        ],
                        **{k: round(v, 4) for k, v in m.items()},
                    }
                )
        agg = {k: round(statistics.mean(x[k] for x in per), 4) for k in per[0]}
        agg["n"] = len(per)
        agg["latency_p50_s"] = round(statistics.median(lat), 3)
        agg["latency_p95_s"] = round(sorted(lat)[int(0.95 * (len(lat) - 1))], 3)
        out["personas"][persona] = agg
        all_rows += per
    if all_rows:
        out["overall"] = {k: round(statistics.mean(x[k] for x in all_rows), 4) for k in all_rows[0]}
        out["n_jobs"] = len(all_rows)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="v0_naive")
    ap.add_argument("--personas", default="ai_ml,fullstack,data_analyst")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--tag", default="", help="suffix for result files/summary keys, e.g. _subset20"
    )
    ap.add_argument(
        "--rows", action="store_true", help="also write rag_<variant><tag>_rows.jsonl per query"
    )
    args = ap.parse_args()
    variants = [v for v in args.variants.split(",") if v]
    personas = [p for p in args.personas.split(",") if p]
    for v in variants:
        if v not in VARIANTS:
            ap.error(f"unknown variant {v}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    res = Resources()
    summary_path = RESULTS / f"rag_summary{args.tag}.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    for v in variants:
        qrows: list[dict[str, Any]] | None = [] if args.rows else None
        result = run_variant(v, personas, args.limit, res, qrows)
        if qrows is not None:
            with (RESULTS / f"rag_{v}{args.tag}_rows.jsonl").open("w", encoding="utf-8") as f:
                f.writelines(json.dumps(q) + "\n" for q in qrows)
        result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (RESULTS / f"rag_{v}{args.tag}.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        result["limit_per_persona"] = args.limit
        summary[f"{v}{args.tag}"] = {
            "overall": result.get("overall"),
            "personas": result["personas"],
            "n_jobs": result["n_jobs"],
            "timestamp": result["timestamp"],
        }
        ov = result.get("overall") or {}
        print(
            f"{v:16s} n={result['n_jobs']:3d}  R@5={ov.get('recall@5', 0):.3f}  MRR={ov.get('mrr', 0):.3f}  nDCG@10={ov.get('ndcg@10', 0):.3f}"
        )
        for p, m in result["personas"].items():
            print(
                f"    {p:13s} n={m['n']:3d}  R@5={m['recall@5']:.3f}  MRR={m['mrr']:.3f}  nDCG@10={m['ndcg@10']:.3f}  p95={m['latency_p95_s']}s"
            )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
