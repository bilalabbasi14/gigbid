"""Proposal quality (B3, B4): unsupported claims per proposal before and after claim verification,
Critic pass rate and revisions, compliance catches, length, latency and cost per proposal.
Optionally submits the final drafts to GigSim with a dedicated evaluation account and records
the simulated client's reaction (reply and hire rate on a fixed job set).

  uv run python -m evals.runners.proposal_eval --per-persona 4 [--variant v2_hybrid] [--gigsim] [--out proposal_eval]

Drafting is forced for every sampled bid-labelled job (even if the decision node would skip it)
so proposal quality is measured on the same jobs for every configuration. The evaluation never
touches a real marketplace: --gigsim requires GIGSIM_BASE_URL to be the simulator. Resumable
like decision_eval (<out>_rows.jsonl; exit status 3 = partial, rerun later).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from typing import Any

import httpx

from agent import settings
from agent.marketplace_port import ProposalDraftIn
from agent.nodes import pricing
from evals.runners.harness import (
    PERSONAS,
    QuotaGuard,
    RowLog,
    analyse,
    cost,
    draft,
    load_dev,
    make_deps,
    summary_stats,
    write_result,
)
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter


def bid_jobs(per_persona: int, seed: int, personas: tuple[str, ...]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for p in personas:
        rows = [
            r
            for r in load_dev(p)
            if r.get("gold_decision") == "bid" and r["label_source"] == "past_proposal"
        ]
        rng.shuffle(rows)
        out += rows[:per_persona]
    return out


async def gigsim_account() -> tuple[str, str]:
    base = settings.env().gigsim_base_url.rstrip("/")
    key = f"eval-{int(time.time())}-{random.randint(1000, 9999)}"  # noqa: S311
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{base}/admin/accounts",
            params={"api_key": key, "freelancer_id": key, "connects": 5000},
        )
        r.raise_for_status()
    return base, key


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.variant:
        settings.config().rag["variant"] = args.variant
    deps = make_deps()
    jobs = bid_jobs(args.per_persona, args.seed, tuple(args.personas.split(",")))
    log = RowLog(
        args.out, extra={"gigsim": args.gigsim}, fresh=args.fresh, retry_errors=args.retry_errors
    )
    guard = QuotaGuard()
    todo = [r for r in jobs if not log.get(r["job_id"])]
    adapter = None
    if args.gigsim:
        base, key = await gigsim_account()
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{base}/admin/open", json=[r["job_id"] for r in todo])
        adapter = GigSimAdapter(base_url=base, token=key)
    sem = asyncio.Semaphore(args.concurrency)

    async def one(row: dict[str, Any]) -> None:
        async with sem:
            if guard.stopped:
                return
            mark = guard.mark()
            try:
                st, t_an = await analyse(row, deps)
                if "price_quote" not in st:  # force a price so every sampled job gets a draft
                    q = pricing.quote(
                        st["job"],
                        st.get("job_spec", {}),
                        st.get("fit_report", {}),
                        st.get("risk_report", {}),
                        st.get("user_prefs", {}),
                        deps.stats(),
                        deps.config,
                        None,
                        int(deps.config.policy_version),
                    )
                    st["price_quote"] = q.model_dump()
                st, t_dr = await draft(st, deps)
            except Exception as exc:  # noqa: BLE001
                if guard.spoiled(mark, exc):
                    return
                log.add(
                    row["job_id"],
                    {
                        "job_id": row["job_id"],
                        "persona": row["persona"],
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    },
                )
                return
        if guard.spoiled(mark):
            return
        d = st.get("proposal_draft", {})
        v = d.get("verification", {})
        claims = d.get("claims", [])
        first = st.get("_first_draft", {})  # type: ignore[typeddict-item]
        out: dict[str, Any] = {
            "job_id": row["job_id"],
            "persona": row["persona"],
            "title": row["job"]["title"][:90],
            "pred_decision": st.get("decision", {}).get("decision"),
            "claims": len(claims),
            "unsupported_before": (v.get("before") or {}).get("unsupported", 0),
            "partly_before": (v.get("before") or {}).get("partly_supported", 0),
            "unsupported_after": sum(
                1
                for c in claims
                if c.get("label") == "unsupported"
                and c.get("action") not in ("removed", "rewritten")
            ),
            "unsupported_rate_before": v.get("unsupported_rate_before"),
            "unsupported_rate_after": v.get("unsupported_rate_after"),
            "removed": v.get("removed", 0),
            "rewritten": v.get("rewritten", 0),
            "critic_passed": bool((st.get("critique") or {}).get("passed")),
            "revisions": int(st.get("revision_count", 0)),
            "critic_issues": (st.get("critique") or {}).get("issues", [])[:4],
            "compliance_allowed": bool((st.get("compliance_verdict") or {}).get("allowed")),
            "compliance_violations": [
                x.get("rule_id") for x in (st.get("compliance_verdict") or {}).get("violations", [])
            ],
            "words": d.get("word_count"),
            "first_draft_words": first.get("word_count"),
            "evidence_cited": len(d.get("evidence_ids", [])),
            "latency_s_analysis": round(t_an, 2),
            "latency_s_proposal": round(t_an + t_dr, 2),
            "tokens": sum(st.get("usage", {}).values()),
            "cost_usd": cost(st.get("usage", {})),
            "cover_letter": d.get("cover_letter", ""),
            "evidence_titles": [e.get("title") for e in st.get("evidence", [])[:8]],
        }
        if adapter is not None and out["compliance_allowed"]:
            pq = st["price_quote"]
            try:
                res = await adapter.submit_proposal(
                    ProposalDraftIn(
                        job_id=row["job_id"],
                        cover_letter=d["cover_letter"][:5000],
                        bid_amount=float(pq["amount"]),
                        bid_type=pq["bid_type"],
                        screening_answers=d.get("screening_answers", []),
                        idempotency_key=f"eval-{row['job_id']}-{args.seed}",
                    )
                )
                out["gigsim_status"] = res.status
            except Exception as exc:  # noqa: BLE001
                out["gigsim_status"] = f"error: {exc}"[:120]
        log.add(row["job_id"], out)
        print(
            f"  {row['persona']:12s} claims={out['claims']:2d} unsup {out['unsupported_before']}->{out['unsupported_after']} critic={out['critic_passed']!s:5s} rev={out['revisions']} {out.get('gigsim_status', '')} {out['latency_s_proposal']:6.1f}s"
        )

    await asyncio.gather(*(one(r) for r in todo))
    return log.collect([r["job_id"] for r in jobs], guard)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if "error" not in r]
    n = len(ok) or 1
    sent = [
        r for r in ok if r.get("gigsim_status") and not str(r["gigsim_status"]).startswith("error")
    ]
    replied = [r for r in sent if r["gigsim_status"] in ("replied", "interview", "hired")]
    return {
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "unsupported_claims_per_proposal_before": round(
            sum(r["unsupported_before"] for r in ok) / n, 3
        ),
        "unsupported_claims_per_proposal_after": round(
            sum(r["unsupported_after"] for r in ok) / n, 3
        ),
        "unsupported_rate_before": round(sum(r["unsupported_rate_before"] or 0 for r in ok) / n, 3),
        "unsupported_rate_after": round(sum(r["unsupported_rate_after"] or 0 for r in ok) / n, 3),
        "critic_pass_rate": round(sum(1 for r in ok if r["critic_passed"]) / n, 3),
        "mean_revisions": round(sum(r["revisions"] for r in ok) / n, 2),
        "compliance_blocked": sum(1 for r in ok if not r["compliance_allowed"]),
        "mean_words": round(sum(r["words"] or 0 for r in ok) / n, 1),
        "latency_s_per_proposal": summary_stats([r["latency_s_proposal"] for r in ok]),
        "cost_usd_per_proposal": summary_stats([r["cost_usd"] for r in ok]),
        "gigsim": {
            "submitted": len(sent),
            "reply_rate": round(len(replied) / len(sent), 3) if sent else None,
            "hire_rate": round(sum(1 for r in sent if r["gigsim_status"] == "hired") / len(sent), 3)
            if sent
            else None,
            "statuses": {
                s: sum(1 for r in sent if r["gigsim_status"] == s)
                for s in ("submitted", "viewed", "replied", "interview", "hired", "lost")
            },
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--personas", default=",".join(PERSONAS))
    ap.add_argument(
        "--variant", default=None, help="RAG variant for evidence retrieval (default: config)"
    )
    ap.add_argument(
        "--gigsim",
        action="store_true",
        help="submit final drafts to the GigSim simulator and record client reactions",
    )
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--out", default="proposal_eval")
    ap.add_argument("--fresh", action="store_true", help="discard saved rows and start over")
    ap.add_argument("--retry-errors", action="store_true", help="rerun items that errored")
    args = ap.parse_args()
    if args.gigsim and "upwork" in settings.env().gigsim_base_url:
        raise SystemExit("refusing: --gigsim must target the simulator")
    rows = asyncio.run(run(args))
    agg = aggregate(rows)
    path = write_result(
        args.out,
        {
            "config": {
                **vars(args),
                "variant": args.variant or settings.config().rag.get("variant"),
                "model_profile": os.environ.get("MODEL_PROFILE", "open"),
            },
            "overall": agg,
            "rows": rows,
        },
    )
    print(
        f"\nunsupported/proposal {agg['unsupported_claims_per_proposal_before']} -> {agg['unsupported_claims_per_proposal_after']}  critic pass {agg['critic_pass_rate']}  reply rate {agg['gigsim']['reply_rate']}  p95 {agg['latency_s_per_proposal']['p95']} s -> {path}"
    )


if __name__ == "__main__":
    main()
