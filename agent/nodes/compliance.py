"""Compliance Guard: enforce data/policy_pack/policy.yaml on the draft. Detectors are rule-based
(contact details, off-platform asks, guarantees, free work, unsupported claims); 'rewrite'
severity triggers a minimal LLM edit, 'block' stops the run with a visible reason."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from agent import settings
from agent.deps import Deps
from agent.handoffs import ComplianceVerdict, ComplianceViolation
from agent.nodes._common import llm_event, node_output, obs
from agent.pii import EMAIL, HANDLE, PHONE, contains_contact_details
from agent.state import BidState
from agent.structured import call_prompt

NODE = "compliance"
URL = re.compile(r"https?://\S+|www\.\S+", re.I)


@lru_cache(maxsize=1)
def policy() -> dict[str, Any]:
    return yaml.safe_load(
        (settings.ROOT / "data/policy_pack/policy.yaml").read_text(encoding="utf-8")
    )


def check_text(text: str, claims: list[dict[str, Any]] | None = None) -> list[ComplianceViolation]:
    pol = policy()
    kw = pol.get("keywords", {})
    sev = {r["id"]: r["severity"] for r in pol.get("rules", [])}
    v: list[ComplianceViolation] = []
    low = text.lower()
    contact = contains_contact_details(text)
    if contact or URL.search(text):
        spans = [m.group(0) for rx in (EMAIL, PHONE, HANDLE, URL) for m in rx.finditer(text)][:3]
        v.append(
            ComplianceViolation(
                rule_id="no_off_platform_contact",
                severity=sev.get("no_off_platform_contact", "block"),
                detail=f"contact details or links: {', '.join(contact) or 'link'}",
                span="; ".join(spans),
            )
        )
    for k in kw.get("off_platform", []):
        if k in low:
            v.append(
                ComplianceViolation(
                    rule_id="no_off_platform_contact",
                    severity=sev.get("no_off_platform_contact", "block"),
                    detail=f"off-platform keyword '{k}'",
                    span=k,
                )
            )
            break
    for k in kw.get("free_work", []):
        if k in low:
            v.append(
                ComplianceViolation(
                    rule_id="no_free_work",
                    severity=sev.get("no_free_work", "block"),
                    detail=f"offers or accepts unpaid work: '{k}'",
                    span=k,
                )
            )
            break
    for k in kw.get("guarantee", []):
        m = re.search(rf"\b{re.escape(k)}\b", low)
        if m:
            v.append(
                ComplianceViolation(
                    rule_id="no_guarantees",
                    severity=sev.get("no_guarantees", "rewrite"),
                    detail=f"guarantee language '{k}'",
                    span=text[max(0, m.start() - 40) : m.end() + 40],
                )
            )
            break
    for c in claims or []:
        if c.get("label") == "unsupported" and c.get("action") not in ("removed", "rewritten"):
            v.append(
                ComplianceViolation(
                    rule_id="no_fabrication",
                    severity=sev.get("no_fabrication", "block"),
                    detail="unsupported claim remains in the draft",
                    span=c.get("text", "")[:160],
                )
            )
    return v


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
                violations="\n".join(f"- {x.rule_id}: {x.detail} ({x.span})" for x in rewrites),
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
