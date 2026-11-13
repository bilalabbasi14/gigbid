"""CI smoke evaluation (E2): a 30-job decision run plus proposals, checked against
evals/thresholds.yaml (one block per model profile). Exits non-zero when bid-or-skip F1 drops,
scam recall drops, unsupported claims rise or latency exceeds the budget. Needs the persona index
(Postgres) and the profile's models: in CI that is the local profile on Ollama, so pull requests
spend no API quota.
  uv run python -m evals.runners.smoke_eval --jobs 30 --proposals 1 --thresholds evals/thresholds.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml

from agent import settings
from evals.runners import decision_eval, proposal_eval
from evals.runners.harness import write_result

PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=30)
    ap.add_argument("--proposals", type=int, default=1)
    ap.add_argument("--thresholds", default="evals/thresholds.yaml")
    args = ap.parse_args()
    profile = os.environ.get("MODEL_PROFILE") or settings.config().models.profile
    th = yaml.safe_load(Path(args.thresholds).read_text(encoding="utf-8"))["smoke"][profile]
    dargs = argparse.Namespace(
        per_persona=max(1, args.jobs // 3),
        seed=3,
        concurrency=2,
        out="smoke_decisions",
        fresh=True,  # a smoke run measures this commit, never resumes an older one
        retry_errors=False,
    )
    dec = decision_eval.score(asyncio.run(decision_eval.run(dargs, PERSONAS)))
    prop = None
    if args.proposals > 0:
        n = args.proposals
        pargs = argparse.Namespace(
            per_persona=max(1, n // 3),
            seed=3,
            personas=",".join(PERSONAS[: min(3, n)]),
            variant=None,
            gigsim=False,
            concurrency=1,
            out="smoke_proposals",
            fresh=True,
            retry_errors=False,
        )
        prop = proposal_eval.aggregate(asyncio.run(proposal_eval.run(pargs)))
    checks = {
        "bid_skip_f1": (dec["bid_skip"]["f1"], ">=", th["min_bid_skip_f1"]),
        "scam_recall": (dec["scam"]["recall"], ">=", th["min_scam_recall"]),
        **(
            {
                "unsupported_claims_per_proposal": (
                    prop["unsupported_claims_per_proposal_after"],
                    "<=",
                    th["max_unsupported_claims_per_proposal"],
                )
            }
            if prop
            else {}
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
            "model_profile": profile,
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
