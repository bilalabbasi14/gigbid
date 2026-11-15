"""Token profile per node (E5 budgets): where the tokens of one analysed job and one proposal go,
per model tier, and how many jobs and proposals a day fit under a per-model daily token cap.

  uv run python -m evals.runners.token_profile --per-persona 2 [--allow-fallback] [--out token_profile]

Runs analysis and drafting (no submission) on bid-labelled dev jobs and sums the usage of every
LLM call in the execution trace. `--allow-fallback` lets a capped model fall back (the models
actually used are recorded), which is fine for measuring prompt sizes but not for quality.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import defaultdict
from typing import Any

from agent import settings
from agent.nodes import pricing
from evals.runners.harness import PERSONAS, analyse, draft, make_deps, write_result
from evals.runners.proposal_eval import bid_jobs

ANALYSIS_NODES = {"analyst", "risk_assessor", "fit_matcher", "intent_classifier", "scout"}


def tier_of(node: str) -> str:
    return settings.config().models.nodes.get(node, "small")


async def profile(args: argparse.Namespace) -> list[dict[str, Any]]:
    deps = make_deps()
    jobs = bid_jobs(args.per_persona, args.seed, PERSONAS)
    out = []
    for row in jobs:
        st, t_an = await analyse(row, deps)
        if "price_quote" not in st:
            st["price_quote"] = pricing.quote(
                st["job"],
                st.get("job_spec", {}),
                st.get("fit_report", {}),
                st.get("risk_report", {}),
                st.get("user_prefs", {}),
                deps.stats(),
                deps.config,
                None,
                int(deps.config.policy_version),
            ).model_dump()
        n_analysis = len(st.get("trace", []))
        st, t_dr = await draft(st, deps)
        calls = []
        for i, ev in enumerate(st.get("trace", [])):
            if ev.get("kind") != "llm":
                continue
            u = (ev.get("result") or {}).get("usage") or {}
            calls.append(
                {
                    "node": ev["node"],
                    "prompt": ev.get("name"),
                    "model": (ev.get("args") or {}).get("model"),
                    "stage": "analysis" if i < n_analysis else "proposal",
                    "input_tokens": int(u.get("input_tokens", 0)),
                    "output_tokens": int(u.get("output_tokens", 0)),
                    "ms": ev.get("duration_ms"),
                }
            )
        out.append(
            {
                "job_id": row["job_id"],
                "persona": row["persona"],
                "latency_s_analysis": round(t_an, 1),
                "latency_s_proposal": round(t_an + t_dr, 1),
                "revisions": int(st.get("revision_count", 0)),
                "calls": calls,
            }
        )
        tot = sum(c["input_tokens"] + c["output_tokens"] for c in calls)
        print(f"  {row['persona']:12s} {row['job_id']} {len(calls)} calls {tot} tokens")
    return out


def summarise(rows: list[dict[str, Any]], daily_cap: int) -> dict[str, Any]:
    n = len(rows) or 1
    per_node: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    per_tier = {
        stage: defaultdict(float) for stage in ("analysis", "proposal")
    }  # tokens per job, by tier
    models: set[str] = set()
    for r in rows:
        for c in r["calls"]:
            key = f"{c['node']}:{c['prompt']}"
            per_node[key]["calls"] += 1 / n
            per_node[key]["input_tokens"] += c["input_tokens"] / n
            per_node[key]["output_tokens"] += c["output_tokens"] / n
            per_tier[c["stage"]][tier_of(c["node"])] += (c["input_tokens"] + c["output_tokens"]) / n
            if c["model"]:
                models.add(c["model"])
    analysis = {t: round(v) for t, v in per_tier["analysis"].items()}
    proposal = {
        t: round(per_tier["analysis"].get(t, 0) + per_tier["proposal"].get(t, 0))
        for t in ("small", "medium", "large")
    }

    def per_day(tokens: dict[str, int]) -> dict[str, Any]:
        caps = {t: daily_cap // v for t, v in tokens.items() if v}
        bottleneck = min(caps, key=caps.get) if caps else None
        return {"by_tier": caps, "bottleneck_tier": bottleneck, "max": caps.get(bottleneck)}

    return {
        "n_jobs": len(rows),
        "models_used": sorted(models),
        "per_call_type": {
            k: {kk: round(vv, 2) for kk, vv in v.items()}
            for k, v in sorted(per_node.items(), key=lambda kv: -kv[1]["input_tokens"])
        },
        "tokens_per_job_analysed_by_tier": analysis,
        "tokens_per_proposal_by_tier": proposal,
        "daily_token_cap_per_model": daily_cap,
        "jobs_analysed_per_day": per_day(analysis),
        "proposals_per_day": per_day(proposal),
        "latency_s_analysis_mean": round(sum(r["latency_s_analysis"] for r in rows) / n, 1),
        "latency_s_proposal_mean": round(sum(r["latency_s_proposal"] for r in rows) / n, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=2)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--daily-cap", type=int, default=200_000, help="tokens/day/model (Groq free)")
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--out", default="token_profile")
    args = ap.parse_args()
    if args.allow_fallback:
        os.environ["GIGBID_STRICT_MODELS"] = "0"
    rows = asyncio.run(profile(args))
    summary = summarise(rows, args.daily_cap)
    path = write_result(args.out, {"config": vars(args), "summary": summary, "rows": rows})
    print(
        f"per job analysed {summary['tokens_per_job_analysed_by_tier']}  per proposal "
        f"{summary['tokens_per_proposal_by_tier']}  -> {summary['jobs_analysed_per_day']['max']} "
        f"jobs/day, {summary['proposals_per_day']['max']} proposals/day -> {path}"
    )


if __name__ == "__main__":
    main()
