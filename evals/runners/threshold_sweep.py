"""Bid threshold sweep on saved decisions, without any model call.

The Decision node is rules over the analyses (agent/nodes/decision.py), so for jobs whose outcome
was set by the fit threshold alone (not by risk, the user's floor or the minimum project size) a
different `thresholds.bid_min_fit_score` changes the outcome predictably. This replays those jobs
at several thresholds and reports bid-or-skip precision, recall and F1.

  uv run python -m evals.runners.threshold_sweep [--results decision_eval]
Writes evals/results/threshold_sweep.json.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from agent import settings
from evals.runners.decision_eval import f1
from evals.runners.harness import RESULTS, write_result


def fit_driven(row: dict[str, Any]) -> bool:
    """The outcome came from the fit comparison, not an earlier rule."""
    reasons = " ".join(row.get("reasons") or []).lower()
    blocked = any(
        k in reasons for k in ("scam likely", "risk ", "below the user's", "minimum project")
    )
    return row.get("fit_score") is not None and not blocked


def sweep(
    rows: list[dict[str, Any]], thresholds: list[float], current: float
) -> list[dict[str, Any]]:
    out = []
    labelled = [r for r in rows if r["gold_decision"] in ("bid", "skip") and not r.get("error")]
    for t in thresholds:
        tp = fp = fn = 0
        changed = 0
        for r in labelled:
            pred = r["pred_decision"]
            if fit_driven(r):
                new = "bid" if float(r["fit_score"]) >= t else ("skip" if pred == "bid" else pred)
                if (new == "bid") != (pred == "bid"):
                    changed += 1
                pred = new
            tp += pred == "bid" and r["gold_decision"] == "bid"
            fp += pred == "bid" and r["gold_decision"] == "skip"
            fn += pred != "bid" and r["gold_decision"] == "bid"
        out.append(
            {
                "bid_min_fit_score": t,
                "shipped": t == current,
                "decisions_changed": changed,
                **f1(tp, fp, fn),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="decision_eval")
    args = ap.parse_args()
    data = json.loads((RESULTS / f"{args.results}.json").read_text(encoding="utf-8"))
    current = float(settings.config().thresholds.get("bid_min_fit_score", 0.6))
    grid = sorted({0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, current})
    rows = sweep(data["rows"], grid, current)
    path = write_result(
        "threshold_sweep",
        {
            "source": f"{args.results}.json",
            "n_fit_driven": sum(fit_driven(r) for r in data["rows"]),
            "note": "evidence-count rule assumed met when the fit threshold is lowered",
            "sweep": rows,
        },
    )
    for r in rows:
        mark = " (shipped)" if r["shipped"] else ""
        print(
            f"t={r['bid_min_fit_score']:.2f}{mark}: P {r['precision']} R {r['recall']} F1 {r['f1']} changed {r['decisions_changed']}"
        )
    print(f"-> {path}")


if __name__ == "__main__":
    main()
