"""Decision node: skip, watch or bid from the three parallel analyses. Pure rules over
agent/config.yaml thresholds, so the choice is explainable and the policy update is a config edit."""

from __future__ import annotations

from typing import Any

from agent.deps import Deps
from agent.handoffs import BidDecision
from agent.nodes._common import node_output, obs
from agent.state import BidState

NODE = "decision"


def decide(
    fit: dict[str, Any],
    risk: dict[str, Any],
    spec: dict[str, Any],
    prefs: dict[str, Any],
    cfg: dict[str, float],
    autonomy: dict[str, Any],
) -> BidDecision:
    reasons: list[str] = []
    fit_score = float(fit.get("score", 0.0))
    risk_score = float(risk.get("score", 0.0))

    if risk.get("scam_likely") or risk_score >= cfg.get("scam_block_score", 0.85):
        reasons.append(
            f"scam likely (risk {risk_score:.2f}): {', '.join(risk.get('flags', [])[:4])}"
        )
        return BidDecision(
            decision="skip", reasons=reasons, fit_score=fit_score, risk_score=risk_score, auto=True
        )
    if risk.get("injection_detected"):
        reasons.append(
            f"prompt-injection text in the post ({', '.join(risk.get('injection_patterns', [])[:3])}); treated as a red flag"
        )
    if risk_score >= cfg.get("max_risk_score", 0.7):
        reasons.append(f"risk {risk_score:.2f} above the maximum {cfg.get('max_risk_score', 0.7)}")
        return BidDecision(
            decision="skip", reasons=reasons, fit_score=fit_score, risk_score=risk_score, auto=True
        )

    floor = float(prefs.get("hourly_floor") or prefs.get("min_hourly") or 0)
    if (
        spec.get("budget_type") == "hourly"
        and spec.get("budget_max")
        and floor
        and float(spec["budget_max"]) < floor
    ):
        reasons.append(
            f"client's maximum hourly {spec['budget_max']} is below the user's floor {floor}"
        )
        return BidDecision(
            decision="skip", reasons=reasons, fit_score=fit_score, risk_score=risk_score, auto=True
        )
    min_budget = float(prefs.get("min_project_budget") or 0)
    if (
        spec.get("budget_type") == "fixed"
        and spec.get("budget_max")
        and min_budget
        and float(spec["budget_max"]) < min_budget
    ):
        reasons.append(
            f"fixed budget {spec['budget_max']} is below the user's minimum project size {min_budget}"
        )
        return BidDecision(
            decision="skip", reasons=reasons, fit_score=fit_score, risk_score=risk_score, auto=True
        )

    none_count = sum(1 for m in fit.get("matrix", []) if m.get("strength") == "none")
    if fit_score >= cfg.get("bid_min_fit_score", 0.6) and len(fit.get("evidence_ids", [])) >= int(
        cfg.get("min_evidence_items", 2)
    ):
        reasons.append(
            f"fit {fit_score:.2f} with {len(fit.get('evidence_ids', []))} evidence items; {none_count} requirement(s) without evidence"
        )
        reasons += [r for r in fit.get("reasons", [])[:2]]
        return BidDecision(
            decision="bid", reasons=reasons, fit_score=fit_score, risk_score=risk_score
        )
    if fit_score >= cfg.get("watch_min_fit_score", 0.45):
        reasons.append(
            f"fit {fit_score:.2f} is borderline; watch for more detail or a better match"
        )
        return BidDecision(
            decision="watch", reasons=reasons, fit_score=fit_score, risk_score=risk_score
        )
    reasons.append(
        f"fit {fit_score:.2f} below the watch threshold; missing: {', '.join(fit.get('missing_skills', [])[:4]) or 'core requirements'}"
    )
    return BidDecision(
        decision="skip",
        reasons=reasons,
        fit_score=fit_score,
        risk_score=risk_score,
        auto=bool(autonomy.get("auto_skip_low_fit", True)),
    )


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    cfg = deps.config
    d = decide(
        state.get("fit_report", {}),
        state.get("risk_report", {}),
        state.get("job_spec", {}),
        state.get("user_prefs", {}),
        cfg.thresholds,
        cfg.autonomy,
    )
    status = {"bid": "pricing", "watch": "watch", "skip": "skipped"}[d.decision]
    return node_output(
        NODE,
        status,
        [obs(NODE, f"decision: {d.decision}", **d.model_dump())],
        decision=d.model_dump(),
    )
