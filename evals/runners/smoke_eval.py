"""CI smoke evaluation (E2): a small decision run plus a few proposals, checked against
evals/thresholds.yaml. Exits non-zero when bid-or-skip F1 drops, scam recall drops, unsupported
claims rise or latency exceeds the budget. Needs the persona index (Postgres) and a model key.

  uv run python -m evals.runners.smoke_eval --jobs 30 --thresholds evals/thresholds.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from evals.runners import decision_eval, proposal_eval
from evals.runners.harness import write_result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=30)
    ap.add_argument("--proposals", type=int, default=3)
    ap.add_argument("--thresholds", default="evals/thresholds.yaml")
    args = ap.parse_args()
    th = yaml.safe_load(Path(args.thresholds).read_text(encoding="utf-8"))["smoke"]
    per_persona = max(1, args.jobs // 3)
    rows = asyncio.run(
        decision_eval.run(
            per_persona, seed=3, personas=("ai_ml", "fullstack", "data_analyst"), concurrency=2
        )
    )
    dec = decision_eval.score(rows)
    pargs = argparse.Namespace(
        per_persona=max(1, args.proposals // 3),
        seed=3,
        personas="ai_ml,fullstack,data_analyst",
        variant=None,
        gigsim=False,
        concurrency=1,
        out="smoke_proposals",
    )
    prows = asyncio.run(proposal_eval.run(pargs))
    prop = proposal_eval.aggregate(prows)
    checks = {
        "bid_skip_f1": (dec["bid_skip"]["f1"], ">=", th["min_bid_skip_f1"]),
        "scam_recall": (dec["scam"]["recall"], ">=", th["min_scam_recall"]),
        "unsupported_claims_per_proposal": (
            prop["unsupported_claims_per_proposal_after"],
            "<=",
            th["max_unsupported_claims_per_proposal"],
        ),
        "p95_latency_s_per_job": (
            dec["latency_s_per_job"]["p95"] or 0,
            "<=",
            th["max_p95_latency_seconds_per_job"],
        ),
    }
    failed = [k for k, (v, op, lim) in checks.items() if (v < lim if op == ">=" else v > lim)]
    write_result(
        "smoke_eval",
        {
            "decisions": dec,
            "proposals": prop,
            "checks": {
                k: {"value": v, "op": op, "threshold": lim} for k, (v, op, lim) in checks.items()
            },
            "failed": failed,
        },
    )
    for k, (v, op, lim) in checks.items():
        print(f"{'FAIL' if k in failed else 'ok  '} {k:34s} {v} {op} {lim}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
