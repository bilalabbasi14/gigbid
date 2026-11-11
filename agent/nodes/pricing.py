"""Pricing Strategist: market quantiles + client budget + user floor + Connects economics.
Deterministic (no LLM) so every number in the rationale is reproducible. Policy-driven values
(Connects costs, boost rules) come from the marketplace policy and config."""

from __future__ import annotations

from typing import Any

from agent.deps import Deps
from agent.handoffs import PriceQuote
from agent.nodes._common import node_output, obs
from agent.state import BidState, TraceEvent

NODE = "pricing"


def quote(
    job: dict[str, Any],
    spec: dict[str, Any],
    fit: dict[str, Any],
    risk: dict[str, Any],
    prefs: dict[str, Any],
    stats: dict[str, Any],
    cfg: Any,
    connects_balance: int | None,
    policy_version: int,
) -> PriceQuote:
    persona = prefs.get("persona") or job.get("persona") or "ai_ml"
    pst = (stats.get("personas") or {}).get(persona, {})
    bid_type = (
        job.get("payment_type")
        if job.get("payment_type") in ("fixed", "hourly")
        else (
            spec.get("budget_type") if spec.get("budget_type") in ("fixed", "hourly") else "fixed"
        )
    )
    pricing_cfg = cfg.pricing
    target_pct = float(pricing_cfg.get("market_percentile_target", 0.55))
    fit_score = float(fit.get("score", 0.5))
    quality = float(risk.get("client_quality", 0.5))
    rationale: list[str] = []

    if bid_type == "hourly":
        q = pst.get("hourly_min_usd") or {}
        floor = float(prefs.get("hourly_floor") or prefs.get("hourly_rate") or q.get("p25") or 15)
        lo, hi = job.get("hourly_min"), job.get("hourly_max")
        base = float(q.get("p50") or floor)
        if lo and hi:
            base = lo + (hi - lo) * (0.4 + 0.5 * fit_score)
            rationale.append(
                f"client range ${lo:g}-${hi:g}/h, placed at fit-weighted {0.4 + 0.5 * fit_score:.0%}"
            )
        else:
            p25, p75 = q.get("p25"), q.get("p75")
            if p25 and p75:
                base = p25 + (p75 - p25) * (target_pct + 0.3 * (fit_score - 0.5))
                rationale.append(
                    f"market p25-p75 ${p25:g}-${p75:g}/h for {persona}, targeting the {target_pct:.0%} point adjusted for fit"
                )
        rate = float(prefs.get("hourly_rate") or base)
        amount = max(floor, base, min(rate, base * 1.25))
        rationale.append(f"user rate ${rate:g}/h, floor ${floor:g}/h")
        amount = round(amount, 0)
        client_min, client_max = lo, hi
    else:
        q = pst.get("fixed_budget_usd") or {}
        floor = float(prefs.get("min_project_budget") or 50)
        budget = job.get("budget") or spec.get("budget_max")
        if budget:
            base = float(budget) * (0.85 + 0.15 * fit_score)
            rationale.append(
                f"client budget ${float(budget):g}, bidding {0.85 + 0.15 * fit_score:.0%} of it given fit {fit_score:.2f}"
            )
        else:
            p25, p75 = q.get("p25"), q.get("p75")
            base = (p25 + (p75 - p25) * target_pct) if (p25 and p75) else floor * 4
            rationale.append(f"no budget stated; market p25-p75 ${p25}-${p75} for {persona}")
        amount = round(max(floor, base), 0)
        rationale.append(f"floor ${floor:g}")
        client_min, client_max = (
            float(budget) if budget else None,
            float(budget) if budget else None,
        )

    connects_cost = int(job.get("connects_cost") or 0)
    p_win = max(0.03, min(0.6, 0.08 + 0.45 * fit_score * (0.5 + 0.5 * quality)))
    ev = round(p_win * (amount if bid_type == "fixed" else amount * 20), 2)
    worth = (
        connects_cost == 0
        or ev / max(1, connects_cost)
        >= float(pricing_cfg.get("connects_value_threshold", 0.3)) * 10
    )
    rationale.append(
        f"estimated p(win) {p_win:.0%}, expected value ${ev:g} vs {connects_cost} Connects -> {'worth it' if worth else 'not worth the Connects'}"
    )
    weekly = int(prefs.get("weekly_connects_budget") or 0)
    if connects_balance is not None and connects_balance < connects_cost:
        worth = False
        rationale.append(f"balance {connects_balance} below cost {connects_cost}")
    if weekly and int(prefs.get("connects_spent_this_week") or 0) + connects_cost > weekly:
        worth = False
        rationale.append(f"would exceed the weekly Connects budget of {weekly}")
    return PriceQuote(
        bid_type=bid_type,
        amount=float(amount),
        floor=floor,
        market_p25=q.get("p25"),
        market_p50=q.get("p50"),
        market_p75=q.get("p75"),
        client_budget_min=client_min,
        client_budget_max=client_max,
        connects_cost=connects_cost,
        connects_balance=connects_balance,
        expected_value=ev,
        worth_connects=worth,
        rationale="; ".join(rationale),
        policy_version=policy_version,
    )


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    balance = None
    try:
        b = await deps.call_tool(NODE, "marketplace", "get_connects_balance", events)
        balance = int(b.get("balance")) if isinstance(b, dict) else None
    except Exception as exc:  # noqa: BLE001
        events.append(obs(NODE, f"connects balance unavailable: {exc}"[:200]))
    q = quote(
        state["job"],
        state.get("job_spec", {}),
        state.get("fit_report", {}),
        state.get("risk_report", {}),
        state.get("user_prefs", {}),
        deps.stats(),
        deps.config,
        balance,
        int(deps.config.policy_version),
    )
    events.append(
        obs(
            NODE,
            "price quote",
            amount=q.amount,
            bid_type=q.bid_type,
            worth_connects=q.worth_connects,
        )
    )
    status = "drafting" if q.worth_connects else "skipped"
    out = node_output(NODE, status, events, price_quote=q.model_dump())
    if not q.worth_connects:
        d = dict(state.get("decision", {}))
        d.update(
            {
                "decision": "skip",
                "reasons": [
                    *d.get("reasons", []),
                    "not worth the Connects: " + q.rationale.split("; ")[-1],
                ],
            }
        )
        out["decision"] = d
    return out
