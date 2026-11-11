"""Compliance Guard: enforce the policy pack (agent/policy.py) on the draft. 'rewrite' severity
triggers a minimal LLM edit, 'block' stops the run with a visible reason."""

from __future__ import annotations

from typing import Any

from agent import policy
from agent.deps import Deps
from agent.handoffs import ComplianceVerdict, ComplianceViolation
from agent.nodes._common import llm_event, node_output, obs
from agent.state import BidState
from agent.structured import call_prompt

NODE = "compliance"


def check_text(
    text: str, claims: list[dict[str, Any]] | None = None, kind: str = "proposal"
) -> list[ComplianceViolation]:
    return policy.check(text, claims, kind)


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    draft = dict(state["proposal_draft"])
    full = draft["cover_letter"] + "\n" + "\n".join(draft.get("screening_answers", []))
    violations = check_text(full, draft.get("claims"))
    version = int(deps.config.policy_version)
    events = []
    usage = None
    rewritten = None
    blocking = [x for x in violations if x.severity == "block"]
    rewrites = [x for x in violations if x.severity == "rewrite"]
    if rewrites and not blocking:
        try:
            res = await call_prompt(
                NODE,
                "compliance_rewrite",
                invoke=deps.invoke,
                policy_version=version,
                violations="\n".join(
                    f"- {x.rule_id} (rule: {policy.describe(x.rule_id)}): {x.detail}"
                    + (f" [{x.span}]" if x.span else "")
                    for x in rewrites
                ),
                text=draft["cover_letter"],
            )
            events.append(llm_event(NODE, "compliance_rewrite", res))
            usage = res.usage
            candidate = res.text.strip()
            if candidate and not [x for x in check_text(candidate) if x.severity != "warn"]:
                rewritten = candidate
                draft["cover_letter"] = candidate
            else:
                blocking = rewrites  # could not fix cleanly -> block, show reason
        except Exception as exc:  # noqa: BLE001
            events.append(obs(NODE, f"rewrite model unavailable: {exc}"[:200]))
            blocking = rewrites
    allowed = not blocking
    reason = (
        "; ".join(f"{x.rule_id}: {x.detail}" for x in blocking)
        if blocking
        else (
            "rewritten to remove: " + "; ".join(x.detail for x in rewrites)
            if rewritten
            else "no violations"
        )
    )
    verdict = ComplianceVerdict(
        allowed=allowed,
        violations=violations,
        rewritten_cover_letter=rewritten,
        policy_version=version,
        reason=reason,
    )
    events.append(
        obs(
            NODE,
            f"compliance {'allowed' if allowed else 'BLOCKED'}: {reason}"[:300],
            policy_version=version,
        )
    )
    status = "awaiting_approval" if allowed else "blocked"
    return node_output(
        NODE, status, events, usage, compliance_verdict=verdict.model_dump(), proposal_draft=draft
    )
