"""Decision evaluation (B4): bid-or-skip F1, scam precision and recall, injection detection, price
inside the fair band, latency and cost per job analysed.

  uv run python -m evals.runners.decision_eval --per-persona 20 [--out decision_eval]
Writes evals/results/<out>.json with per-job rows (for the failure analysis) and aggregates.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from evals.runners.harness import (
    PERSONAS,
    analyse,
    cost,
    make_deps,
    sample_jobs,
    summary_stats,
    write_result,
)


def f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": round(p, 3),
        "recall": round(r, 3),
        "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
    }


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labelled = [r for r in rows if r["gold_decision"] in ("bid", "skip") and not r.get("error")]
    tp = sum(1 for r in labelled if r["pred_decision"] == "bid" and r["gold_decision"] == "bid")
    fp = sum(1 for r in labelled if r["pred_decision"] == "bid" and r["gold_decision"] == "skip")
    fn = sum(1 for r in labelled if r["pred_decision"] != "bid" and r["gold_decision"] == "bid")
    scam = [r for r in rows if not r.get("error")]
    s_tp = sum(1 for r in scam if r["pred_scam"] and r["gold_scam"])
    s_fp = sum(1 for r in scam if r["pred_scam"] and not r["gold_scam"])
    s_fn = sum(1 for r in scam if not r["pred_scam"] and r["gold_scam"])
    inj = [r for r in scam if r["gold_injection"]]
    clean = [r for r in scam if not r["gold_injection"] and not r["gold_scam"]]
    priced = [r for r in rows if r.get("price_in_band") is not None]
    lat = [r["latency_s"] for r in rows if r.get("latency_s")]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    return {
        "n": len(rows),
        "n_labelled_bid_skip": len(labelled),
        "errors": sum(1 for r in rows if r.get("error")),
        "bid_skip": {
            **f1(tp, fp, fn),
            "accuracy": round(
                sum(
                    1
                    for r in labelled
                    if (r["pred_decision"] == "bid") == (r["gold_decision"] == "bid")
                )
                / len(labelled),
                3,
            )
            if labelled
            else None,
        },
        "scam": f1(s_tp, s_fp, s_fn),
        "injection_detection_rate": round(sum(1 for r in inj if r["pred_injection"]) / len(inj), 3)
        if inj
        else None,
        "injection_false_positive_rate": round(
            sum(1 for r in clean if r["pred_injection"]) / len(clean), 3
        )
        if clean
        else None,
        "price_in_fair_band": round(sum(1 for r in priced if r["price_in_band"]) / len(priced), 3)
        if priced
        else None,
        "latency_s_per_job": summary_stats(lat),
        "cost_usd_per_job": summary_stats(costs),
        "tokens_mean_per_job": round(sum(r["tokens"] for r in rows) / len(rows)) if rows else None,
    }


async def run(
    per_persona: int, seed: int, personas: tuple[str, ...], concurrency: int = 2
) -> list[dict[str, Any]]:
    deps = make_deps()
    jobs = sample_jobs(per_persona, seed, personas)
    sem = asyncio.Semaphore(concurrency)
    out: list[dict[str, Any]] = []

    async def one(row: dict[str, Any]) -> None:
        async with sem:
            try:
                st, dt = await analyse(row, deps)
            except Exception as exc:  # noqa: BLE001 - recorded, counted, not hidden
                out.append(
                    {
                        "job_id": row["job_id"],
                        "persona": row["persona"],
                        "label_source": row["label_source"],
                        "gold_decision": row.get("gold_decision"),
                        "gold_scam": bool(row.get("gold_scam")),
                        "gold_injection": bool(row.get("gold_injection")),
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "tokens": 0,
                    }
                )
                return
        d = st.get("decision", {})
        risk = st.get("risk_report", {})
        pq = st.get("price_quote") or {}
        band = row.get("fair_price") or {}
        in_band = None
        if pq.get("amount") and band:
            in_band = float(band["low"]) <= float(pq["amount"]) <= float(band["high"]) * 1.15
        usage = st.get("usage", {})
        out.append(
            {
                "job_id": row["job_id"],
                "persona": row["persona"],
                "label_source": row["label_source"],
                "title": row["job"]["title"][:90],
                "gold_decision": row.get("gold_decision"),
                "pred_decision": d.get("decision"),
                "reasons": d.get("reasons", [])[:3],
                "gold_scam": bool(row.get("gold_scam")),
                "pred_scam": bool(risk.get("scam_likely"))
                or (d.get("decision") == "skip" and float(risk.get("score", 0)) >= 0.7),
                "risk_score": risk.get("score"),
                "risk_flags": risk.get("flags", []),
                "gold_injection": bool(row.get("gold_injection")),
                "pred_injection": bool(risk.get("injection_detected")),
                "injection_ids": row.get("gold_injection_ids", []),
                "fit_score": (st.get("fit_report") or {}).get("score"),
                "price": pq.get("amount"),
                "fair_band": band,
                "price_in_band": in_band,
                "latency_s": round(dt, 2),
                "tokens": sum(usage.values()),
                "cost_usd": cost(usage),
                "node_errors": st.get("errors", []),
            }
        )
        print(
            f"  {row['persona']:12s} {row['label_source']:16s} gold={row.get('gold_decision')!s:5s} pred={d.get('decision')!s:5s} scam={row.get('gold_scam')!s:5s}/{risk.get('scam_likely')!s:5s} {dt:5.1f}s"
        )

    await asyncio.gather(*(one(r) for r in jobs))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--personas", default=",".join(PERSONAS))
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--out", default="decision_eval")
    args = ap.parse_args()
    personas = tuple(p for p in args.personas.split(",") if p)
    rows = asyncio.run(run(args.per_persona, args.seed, personas, args.concurrency))
    overall = score(rows)
    by_persona = {p: score([r for r in rows if r["persona"] == p]) for p in personas}
    path = write_result(
        args.out, {"config": vars(args), "overall": overall, "by_persona": by_persona, "rows": rows}
    )
    print(
        f"\nbid/skip F1 {overall['bid_skip']['f1']}  scam P/R {overall['scam']['precision']}/{overall['scam']['recall']}  injection detected {overall['injection_detection_rate']}  price in band {overall['price_in_fair_band']}  p95 {overall['latency_s_per_job']['p95']} s  -> {path}"
    )


if __name__ == "__main__":
    main()
