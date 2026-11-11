"""Human approval (C5, R4) and submission. `interrupt()` pauses the graph with the full payload:
draft, evidence behind every claim, risk report, price rationale and the dry-run preview. The
resume value is an ApprovalDecision: approve, edit (diffed, re-checked by Compliance) or reject.
Submission uses an idempotency key derived from the thread so a retry never spends twice."""

from __future__ import annotations

import difflib
import time
from typing import Any

from langgraph.types import interrupt

from agent.deps import Deps
from agent.handoffs import ApprovalDecision, ApprovalPayload, ProposalDraft, SubmissionResult
from agent.nodes._common import node_output, obs
from agent.state import BidState, TraceEvent

NODE_APPROVAL = "approval"
NODE_SUBMIT = "submitter"


def idempotency_key(thread_id: str, job_id: str, revision: int = 0) -> str:
    return f"bid:{thread_id}:{job_id}:r{revision}"[:128]


async def prepare(state: BidState, deps: Deps) -> dict[str, Any]:
    """Build the approval payload including the marketplace dry-run preview (no Connects spent)."""
    events: list[TraceEvent] = []
    draft = ProposalDraft.model_validate(state["proposal_draft"])
    price = state.get("price_quote", {})
    preview: dict[str, Any] = {}
    try:
        res = await deps.call_tool(
            NODE_SUBMIT,
            "marketplace",
            "create_proposal_draft",
            events,
            draft={
                "job_id": draft.job_id,
                "cover_letter": draft.cover_letter,
                "bid_amount": float(price.get("amount", 1)),
                "bid_type": price.get("bid_type", "fixed"),
                "screening_answers": draft.screening_answers,
                "idempotency_key": idempotency_key(
                    state["thread_id"], draft.job_id, draft.revision
                ),
                "dry_run": True,
            },
        )
        preview = (res.get("preview") if isinstance(res, dict) else None) or res
    except Exception as exc:  # noqa: BLE001 - approval still possible; preview shows the error
        events.append(obs(NODE_APPROVAL, f"dry-run preview unavailable: {exc}"[:300]))
        preview = {"error": str(exc)[:300]}
    payload = ApprovalPayload(
        kind="proposal",
        job_id=draft.job_id,
        thread_id=state["thread_id"],
        draft=draft,
        evidence=[
            e for e in state.get("evidence", []) if e.get("evidence_id") in set(draft.evidence_ids)
        ]
        or state.get("evidence", []),
        risk=state.get("risk_report", {}),
        price=price,
        fit=state.get("fit_report"),
        job_spec=state.get("job_spec"),
        critique=state.get("critique"),
        compliance=state.get("compliance_verdict"),
        dry_run_preview=preview,
        connects_cost=int(price.get("connects_cost") or 0),
    )
    return node_output(
        NODE_APPROVAL, "awaiting_approval", events, approval_payload=payload.model_dump()
    )


async def wait_for_human(state: BidState, deps: Deps) -> dict[str, Any]:
    """The interrupt. Everything before this line runs again on resume, which is why the payload is
    built in `prepare` and stored in state."""
    events: list[TraceEvent] = [
        TraceEvent(
            ts=time.time(),
            node=NODE_APPROVAL,
            kind="interrupt",
            name="approval",
            note="waiting for the human",
        )
    ]
    raw = interrupt(state["approval_payload"])
    decision = ApprovalDecision.model_validate(
        raw if isinstance(raw, dict) else {"action": str(raw)}
    )
    events.append(
        TraceEvent(
            ts=time.time(),
            node=NODE_APPROVAL,
            kind="resume",
            name="approval",
            result={"action": decision.action, "reason": decision.reason},
            note="human decided",
        )
    )
    out: dict[str, Any] = {"approval": decision.model_dump()}
    if decision.action == "reject":
        return node_output(NODE_APPROVAL, "rejected", events, **out)
    if decision.action == "edit":
        draft = dict(state["proposal_draft"])
        before = draft["cover_letter"]
        after = decision.edited_cover_letter if decision.edited_cover_letter is not None else before
        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(), after.splitlines(), "agent", "user", lineterm=""
            )
        )
        draft["cover_letter"] = after
        if decision.edited_answers is not None:
            draft["screening_answers"] = decision.edited_answers
        draft["revision"] = int(draft.get("revision", 0)) + 1
        draft["word_count"] = len(after.split())
        out["proposal_draft"] = draft
        out["edit_diff"] = {
            "before": before,
            "after": after,
            "unified": diff,
            "changed": before != after,
            "ts": time.time(),
        }
        events.append(
            obs(
                NODE_APPROVAL,
                "user edited the draft; re-checking compliance",
                changed_lines=diff.count("\n"),
            )
        )
        return node_output(NODE_APPROVAL, "compliance", events, **out)
    return node_output(NODE_APPROVAL, "submitting", events, **out)


async def submit(state: BidState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    draft = ProposalDraft.model_validate(state["proposal_draft"])
    price = state.get("price_quote", {})
    key = idempotency_key(state["thread_id"], draft.job_id, draft.revision)
    try:
        res = await deps.call_tool(
            NODE_SUBMIT,
            "marketplace",
            "submit_proposal",
            events,
            draft={
                "job_id": draft.job_id,
                "cover_letter": draft.cover_letter,
                "bid_amount": float(price.get("amount", 1)),
                "bid_type": price.get("bid_type", "fixed"),
                "screening_answers": draft.screening_answers,
                "idempotency_key": key,
                "dry_run": False,
            },
        )
    except Exception as exc:  # noqa: BLE001
        events.append(obs(NODE_SUBMIT, f"submission failed: {exc}"[:300]))
        return node_output(
            NODE_SUBMIT,
            "needs_attention",
            events,
            errors=[f"submit failed: {exc}"[:300]],
            needs_attention_reason=f"submission failed: {exc}"[:200],
        )
    result = SubmissionResult(
        proposal_id=res.get("proposal_id"),
        status=res.get("status", "submitted"),
        connects_spent=int(res.get("connects_spent") or 0),
        thread_id=res.get("thread_id"),
        idempotent_replay=bool(res.get("idempotent_replay")),
    )
    events.append(obs(NODE_SUBMIT, "proposal submitted", **result.model_dump()))
    return node_output(
        NODE_SUBMIT,
        "submitted",
        events,
        submission=result.model_dump(),
        outcome={"status": result.status, "proposal_id": result.proposal_id},
    )
