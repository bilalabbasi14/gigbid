from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from apps.api.auth.security import CurrentUser
from apps.api.db import JobRecord, PipelineCard, Run, get_session
from apps.api.runtime import runtime
from apps.api.schemas import AnalyticsOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1)))], 1)


@router.get("", response_model=AnalyticsOut)
async def analytics(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalyticsOut:
    cards = (
        await session.scalars(select(PipelineCard).where(PipelineCard.user_id == user.user_id))
    ).all()
    jobs = (await session.scalars(select(JobRecord).where(JobRecord.user_id == user.user_id))).all()
    runs = (await session.scalars(select(Run).where(Run.user_id == user.user_id))).all()

    stages = Counter(c.stage for c in cards)
    order = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
    reached = {
        s: sum(stages[t] for t in order[i:] if t != "lost")
        + (stages["lost"] if s in ("submitted",) else 0)
        for i, s in enumerate(order)
    }
    funnel = {
        "seen": len(jobs),
        "analysed": sum(1 for j in jobs if j.decision),
        "bid": sum(1 for j in jobs if j.decision == "bid"),
        "skipped": sum(1 for j in jobs if j.decision == "skip"),
        **{s: reached.get(s, 0) for s in ("submitted", "viewed", "replied", "interview", "hired")},
        "lost": stages["lost"],
    }

    by_cat: dict[str, dict[str, Any]] = {}
    for c in cards:
        d = by_cat.setdefault(
            c.category or "unknown",
            {
                "category": c.category or "unknown",
                "submitted": 0,
                "replied": 0,
                "hired": 0,
                "connects": 0,
            },
        )
        if c.stage != "drafted":
            d["submitted"] += 1
            d["connects"] += c.connects_spent
        if c.stage in ("replied", "interview", "hired"):
            d["replied"] += 1
        if c.stage == "hired":
            d["hired"] += 1
    for d in by_cat.values():
        d["reply_rate"] = round(d["replied"] / d["submitted"], 3) if d["submitted"] else None
        d["hire_rate"] = round(d["hired"] / d["submitted"], 3) if d["submitted"] else None

    spent = sum(c.connects_spent for c in cards)
    replies = sum(1 for c in cards if c.stage in ("replied", "interview", "hired"))
    connects = {
        "spent": spent,
        "weekly_budget": (user.settings_json or {}).get("weekly_connects_budget"),
        "replies": replies,
        "connects_per_reply": round(spent / replies, 1) if replies else None,
        "hires": stages["hired"],
    }

    bid_runs = [r for r in runs if r.kind == "bid" and r.latency_ms]
    prop_runs = [
        r for r in bid_runs if r.status in ("awaiting_approval", "submitted", "rejected", "blocked")
    ]
    costs = [r.cost_usd for r in bid_runs if r.cost_usd is not None]
    cost_latency = {
        "jobs_analysed": len(bid_runs),
        "latency_p50_s_per_job": _p([r.latency_ms / 1000 for r in bid_runs], 0.5),
        "latency_p95_s_per_job": _p([r.latency_ms / 1000 for r in bid_runs], 0.95),
        "latency_p95_s_per_proposal": _p([r.latency_ms / 1000 for r in prop_runs], 0.95),
        "cost_usd_mean_per_job": round(statistics.mean(costs), 5) if costs else None,
        "cost_usd_mean_per_proposal": round(
            statistics.mean([r.cost_usd for r in prop_runs if r.cost_usd is not None]), 5
        )
        if prop_runs
        else None,
        "tokens_mean_per_job": round(
            statistics.mean([sum((r.usage_json or {}).values()) for r in bid_runs])
        )
        if bid_runs
        else None,
        "budget": {
            k: settings.config().budgets.get(k)
            for k in (
                "latency_p95_seconds_per_job",
                "latency_p95_seconds_per_proposal",
                "cost_usd_per_job_analysed",
                "cost_usd_per_proposal",
            )
        },
    }

    reasons: Counter[str] = Counter()
    for j in jobs:
        if j.decision == "skip" and j.latest_thread_id:
            try:
                values, _ = await runtime().state_values(j.latest_thread_id, "bid", user.user_id)
                for r in (values.get("decision") or {}).get("reasons", [])[:1]:
                    reasons[r.split("(")[0].split(":")[0].strip()[:60]] += 1
            except Exception as exc:  # noqa: BLE001
                log.debug("skip reason unavailable for %s: %s", j.job_id, exc)
                continue
    for r in runs:
        if r.status == "rejected":
            reasons["rejected by user"] += 1
    rejection = [{"reason": k, "count": v} for k, v in reasons.most_common(8)]

    results: dict[str, Any] = {}
    p = settings.ROOT / "evals/results/rag_summary.json"
    if p.exists():
        results = json.loads(p.read_text(encoding="utf-8"))
    return AnalyticsOut(
        funnel=funnel,
        by_category=list(by_cat.values()),
        connects=connects,
        cost_latency=cost_latency,
        rejection_reasons=rejection,
        retrieval_results=results,
    )
