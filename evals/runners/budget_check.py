"""Declared budgets vs measured (E5): p50/p95 latency and cost per job analysed and per proposal.

  uv run python -m evals.runners.budget_check
Cost: every LLM call in the token profiles (evals/results/token_profile*.json) priced at the list
prices in agent/config.yaml (budgets.list_prices_usd_per_million); the free plan itself costs
nothing. Latency: the token profiles plus, when present, the decision and proposal evaluation
rows. Writes evals/results/budget_check.json.
"""

from __future__ import annotations

import json
from typing import Any

from agent import settings
from evals.runners.harness import RESULTS, pctl, write_result


def _price(model: str, tin: int, tout: int, prices: dict[str, list[float]]) -> float:
    pin, pout = prices.get(model, [0.0, 0.0])
    return (tin * pin + tout * pout) / 1_000_000


def _stats(xs: list[float], digits: int) -> dict[str, Any]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "p50": None, "p95": None}
    return {"n": len(xs), "p50": round(pctl(xs, 0.5), digits), "p95": round(pctl(xs, 0.95), digits)}


def main() -> None:
    b = settings.config().budgets
    prices = b.get("list_prices_usd_per_million", {})
    cost_job, cost_prop, lat_job, lat_prop, sources = [], [], [], [], []
    for f in sorted(RESULTS.glob("token_profile*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        sources.append(f.name)
        for r in d["rows"]:
            calls = r["calls"]
            cost_job.append(
                sum(
                    _price(c["model"], c["input_tokens"], c["output_tokens"], prices)
                    for c in calls
                    if c["stage"] == "analysis"
                )
            )
            cost_prop.append(
                sum(
                    _price(c["model"], c["input_tokens"], c["output_tokens"], prices) for c in calls
                )
            )
            lat_job.append(r["latency_s_analysis"])
            lat_prop.append(r["latency_s_proposal"])
    dec = RESULTS / "decision_eval.json"
    if dec.exists():
        sources.append(dec.name)
        lat_job += [
            r.get("latency_s") for r in json.loads(dec.read_text())["rows"] if not r.get("error")
        ]
    for f in sorted(RESULTS.glob("proposal_eval_*.json")):
        sources.append(f.name)
        lat_prop += [
            r.get("latency_s_proposal")
            for r in json.loads(f.read_text())["rows"]
            if not r.get("error")
        ]
    measured = {
        "latency_s_per_job": _stats(lat_job, 1),
        "latency_s_per_proposal": _stats(lat_prop, 1),
        "cost_usd_per_job": _stats(cost_job, 4),
        "cost_usd_per_proposal": _stats(cost_prop, 4),
    }
    declared = {
        "latency_s_per_job": b.get("latency_p95_seconds_per_job"),
        "latency_s_per_proposal": b.get("latency_p95_seconds_per_proposal"),
        "cost_usd_per_job": b.get("cost_usd_per_job_analysed"),
        "cost_usd_per_proposal": b.get("cost_usd_per_proposal"),
    }
    verdict = {
        k: (None if measured[k]["p95"] is None else measured[k]["p95"] <= declared[k])
        for k in declared
    }
    path = write_result(
        "budget_check",
        {
            "sources": sources,
            "prices_usd_per_million": prices,
            "declared_p95": declared,
            "measured": measured,
            "within_budget_at_p95": verdict,
        },
    )
    for k in declared:
        m = measured[k]
        print(
            f"{k:24s} declared {declared[k]}  p50 {m['p50']}  p95 {m['p95']}  n={m['n']}  ok={verdict[k]}"
        )
    print(f"-> {path}")


if __name__ == "__main__":
    main()
