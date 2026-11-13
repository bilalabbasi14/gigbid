"""Offline check of the Risk Assessor's scam rule on every dev job, without any model call.

The rule is deterministic: a post is a likely scam when the heuristic pre-screen scores at least
thresholds.max_risk_score or finds a hard scam signal (agent/config.yaml -> risk). The model can
only raise the pre-screen score, never lower it, so this measures the floor the full pipeline
starts from: scam recall by scam kind and false alarms on every non-scam dev job.

  uv run python -m evals.runners.scam_rule_check --label before   (then again with --label after)
Writes evals/results/scam_rule_check_<label>.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from agent import settings
from agent.nodes.risk_assessor import prescreen
from evals.runners.harness import DATASETS, PERSONAS, load_dev, write_result


def scam_kinds() -> dict[str, str]:
    kinds = {}
    for line in (DATASETS / "adversarial_gold.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        if g.get("scam"):
            kinds[g["job_id"]] = g.get("scam_type") or "scam"
    return kinds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    max_risk = float(settings.config().thresholds.get("max_risk_score", 0.7))
    kinds = scam_kinds()
    rows: list[dict[str, Any]] = []
    for persona in PERSONAS:
        for r in load_dev(persona):
            pre = prescreen(r["job"], r["job"].get("client"))
            hard = pre.get("hard", [])
            flagged = pre["score"] >= max_risk or bool(hard)
            rows.append(
                {
                    "job_id": r["job_id"],
                    "persona": persona,
                    "gold_scam": bool(r.get("gold_scam")),
                    "kind": kinds.get(r["job_id"], "scam") if r.get("gold_scam") else None,
                    "flagged": flagged,
                    "score": pre["score"],
                    "hard": hard,
                    "flags": pre["flags"],
                }
            )
    scams = [r for r in rows if r["gold_scam"]]
    clean = [r for r in rows if not r["gold_scam"]]
    tp = sum(r["flagged"] for r in scams)
    fp = sum(r["flagged"] for r in clean)
    by_kind = {
        k: {"n": n, "caught": sum(r["flagged"] for r in scams if r["kind"] == k)}
        for k, n in Counter(r["kind"] for r in scams).items()
    }
    summary = {
        "n_jobs": len(rows),
        "n_scams": len(scams),
        "scam_recall": round(tp / len(scams), 3) if scams else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "false_alarm_rate": round(fp / len(clean), 3) if clean else None,
        "false_alarms": fp,
        "by_kind": by_kind,
        "false_alarm_jobs": [
            {k: r[k] for k in ("job_id", "persona", "score", "hard", "flags")}
            for r in clean
            if r["flagged"]
        ][:20],
    }
    path = write_result(f"scam_rule_check_{args.label}", {"label": args.label, **summary})
    print(
        f"{args.label}: scams caught {tp}/{len(scams)} (recall {summary['scam_recall']}), "
        f"false alarms {fp}/{len(clean)} ({summary['false_alarm_rate']}) -> {path}"
    )
    for k, v in by_kind.items():
        print(f"  {k:14s} {v['caught']}/{v['n']}")


if __name__ == "__main__":
    main()
