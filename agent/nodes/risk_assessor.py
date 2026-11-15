"""Risk Assessor: client history (marketplace read) + heuristic pre-screen + small-model judgement.

Heuristics come from data/policy_pack (keywords) and injection_patterns.yaml, so a policy update
changes behaviour without code edits."""

from __future__ import annotations

import json
from typing import Any

from agent import policy, settings
from agent.deps import Deps
from agent.guardrails import detect_injection
from agent.handoffs import RiskReport
from agent.nodes._common import job_text, llm_event, node_output, obs
from agent.pii import contains_contact_details
from agent.state import BidState, TraceEvent
from agent.structured import call_structured

NODE = "risk_assessor"


def _risk_cfg() -> tuple[dict[str, float], set[str]]:
    risk = settings.config().risk or {}
    return {k: float(v) for k, v in (risk.get("weights") or {}).items()}, set(
        risk.get("hard_signals") or []
    )


def prescreen(job: dict[str, Any], client: dict[str, Any] | None) -> dict[str, Any]:
    """Heuristic risk score from the post and the client's history. Signal weights and the hard
    signals come from agent/config.yaml (risk), keyword lists from the policy pack."""
    text = f"{job.get('title', '')}\n{job.get('description', '')}".lower()
    kw = policy.load().get("keywords", {})
    weights, hard = _risk_cfg()
    flags: list[str] = []
    score = 0.0

    def hit(name: str) -> None:
        nonlocal score
        flags.append(name)
        score += weights.get(name, 0.0)

    for name in weights:  # every weighted signal with a keyword list in the policy pack
        if name in kw and any(k in text for k in kw[name]):
            hit(name)
    if contains_contact_details(text):
        hit("contact_details_in_post")
    if "http://" in text or "apply through" in text or "register on" in text:
        hit("external_link")
    inj = detect_injection(job.get("description", ""))
    if inj:
        hit("prompt_injection")
    budget = job.get("budget") or 0
    if job.get("payment_type") == "fixed" and budget == 0 and "trial" in text:
        hit("zero_budget_trial")
    if (job.get("hourly_min") or 0) >= 120 and "easy" in text:
        hit("too_good_to_be_true")
    quality = 0.5
    if client:
        quality = 0.2
        if client.get("payment_verified"):
            quality += 0.3
        spent = client.get("total_spent") or 0
        quality += min(0.3, spent / 20000)
        if (client.get("rating") or 0) >= 4.5:
            quality += 0.1
        if (client.get("reviews_count") or 0) >= 5:
            quality += 0.1
        quality = min(1.0, quality)
        if not client.get("payment_verified") and spent == 0:
            hit("unverified_no_spend")
    return {
        "score": round(min(1.0, score), 3),
        "flags": flags,
        "hard": [f for f in flags if f in hard],
        "injection": [h["id"] for h in inj],
        "client_quality": round(quality, 3),
    }


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    job = state["job"]
    client: dict[str, Any] | None = job.get("client")
    if job.get("client_id"):
        try:
            client = await deps.call_tool(
                NODE, "marketplace", "get_client_history", events, client_id=job["client_id"]
            )
        except Exception as exc:  # noqa: BLE001 - degraded: score with what we have
            events.append(obs(NODE, f"client history unavailable: {exc}"[:300]))
    pre = prescreen(job, client)
    events.append(obs(NODE, "heuristic pre-screen", **pre))
    usage = None
    try:
        report, res = await call_structured(
            NODE,
            "risk",
            RiskReport,
            invoke=deps.invoke,
            client_history=json.dumps(
                {k: v for k, v in (client or {}).items() if k != "past_jobs"}, default=str
            )
            if client
            else "unknown client",
            prescreen=json.dumps(pre),
            title=job.get("title", ""),
            job_text=job_text(job),
        )
        events.append(llm_event(NODE, "risk", res))
        usage = res.usage
        # never let the model lower a heuristic injection/scam finding below the pre-screen floor
        report.score = max(report.score, min(1.0, pre["score"] * 0.9))
        report.flags = sorted(set(report.flags) | set(pre["flags"]))
        report.injection_detected = bool(pre["injection"]) or report.injection_detected
        report.injection_patterns = sorted(set(report.injection_patterns) | set(pre["injection"]))
        if report.client_quality == 0.5 and client:
            report.client_quality = pre["client_quality"]
    except Exception as exc:  # noqa: BLE001 - fall back to heuristics so the graph still decides
        events.append(obs(NODE, f"model unavailable, heuristic-only risk: {exc}"[:300]))
        report = RiskReport(
            score=pre["score"],
            flags=pre["flags"],
            injection_detected=bool(pre["injection"]),
            injection_patterns=pre["injection"],
            client_quality=pre["client_quality"],
            explanation="Heuristic-only assessment (model unavailable).",
        )
    _, hard = _risk_cfg()
    report.scam_likely = (
        report.score >= float(settings.config().thresholds.get("max_risk_score", 0.7))
        or bool(pre["hard"])
        or any(f in hard for f in report.flags)
    )
    return node_output(NODE, None, events, usage, risk_report=report.model_dump())
