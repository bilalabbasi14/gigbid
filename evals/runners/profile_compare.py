"""Compare two model profiles on the same dev jobs (spec: at least two open LLM configurations,
with quality, latency and cost; hardware and tokens per second for local models).

  uv run python -m evals.runners.profile_compare --a decision_eval --b decision_eval_local
Reads both decision results, keeps the jobs present in both, scores them the same way and writes
evals/results/profile_comparison.json.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from evals.runners.decision_eval import score
from evals.runners.harness import RESULTS, write_result


def load(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="decision_eval")
    ap.add_argument("--b", default="decision_eval_local")
    args = ap.parse_args()
    a, b = load(args.a), load(args.b)
    ids = {r["job_id"] for r in a["rows"]} & {r["job_id"] for r in b["rows"]}
    out: dict[str, Any] = {"n_shared_jobs": len(ids), "profiles": {}}
    for name, data in ((args.a, a), (args.b, b)):
        rows = [r for r in data["rows"] if r["job_id"] in ids]
        s = score(rows)
        out["profiles"][name] = {
            "model_profile": data.get("model_profile"),
            "hardware": data.get("hardware"),
            "bid_skip": s["bid_skip"],
            "scam": s["scam"],
            "price_in_fair_band": s["price_in_fair_band"],
            "latency_s_per_job": s["latency_s_per_job"],
            "tokens_mean_per_job": s["tokens_mean_per_job"],
            "output_tokens_per_second": s.get("output_tokens_per_second"),
        }
    pa = {r["job_id"]: r["pred_decision"] for r in a["rows"] if r["job_id"] in ids}
    pb = {r["job_id"]: r["pred_decision"] for r in b["rows"] if r["job_id"] in ids}
    out["decision_agreement"] = (
        round(sum(pa[j] == pb[j] for j in ids) / len(ids), 3) if ids else None
    )
    out["per_job"] = [
        {
            "job_id": j,
            "gold": next(r["gold_decision"] for r in a["rows"] if r["job_id"] == j),
            args.a: pa[j],
            args.b: pb[j],
        }
        for j in sorted(ids)
    ]
    path = write_result("profile_comparison", {"a": args.a, "b": args.b, **out})
    for name, p in out["profiles"].items():
        print(
            f"{name:22s} F1 {p['bid_skip']['f1']} acc {p['bid_skip']['accuracy']} scam R {p['scam']['recall']} "
            f"p50 {p['latency_s_per_job']['p50']} s tok/job {p['tokens_mean_per_job']}"
        )
    print(f"agreement {out['decision_agreement']} on {len(ids)} jobs -> {path}")


if __name__ == "__main__":
    main()
