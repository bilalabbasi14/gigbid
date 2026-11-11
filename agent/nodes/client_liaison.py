"""Client Liaison: read new client messages, classify intent, draft a reply (with interview slots
from the Workspace server when asked), run compliance, and stop for approval. Sending happens in
a separate node only after the human approves."""

from __future__ import annotations

import time
from typing import Any

from agent import policy
from agent.deps import Deps
from agent.guardrails import delimit_untrusted, detect_injection
from agent.handoffs import ComplianceVerdict, IntentClassification, ReplyDraft
from agent.nodes._common import llm_event, node_output, obs
from agent.nodes.compliance import check_text
from agent.state import ConversationState, TraceEvent
from agent.structured import call_prompt, call_structured

NODE = "client_liaison"
STAGE_FOR_INTENT = {
    "interview_request": "interview",
    "acceptance": "hired",
    "rejection": "lost",
    "negotiation": "replied",
    "question": "replied",
    "other": "replied",
    "scam_signal": "replied",
}


def _history(messages: list[dict[str, Any]], limit: int = 8) -> str:
    rows = []
    for m in messages[-limit:]:
        who = "Client" if m.get("sender") == "client" else "Me"
        rows.append(
            f"{who}: {delimit_untrusted(m.get('body', ''), 'CLIENT_MESSAGE', max_chars=800) if who == 'Client' else m.get('body', '')}"
        )
    return "\n".join(rows) or "(no earlier messages)"


async def fetch_messages(state: ConversationState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    res = await deps.call_tool(
        NODE, "marketplace", "list_messages", events, thread_id=state["marketplace_thread_id"]
    )
    msgs = res.get("items", []) if isinstance(res, dict) else []
    known = {m.get("message_id") for m in state.get("messages", [])}
    new = [m for m in msgs if m.get("message_id") not in known and m.get("sender") == "client"]
    if not state.get("job") and state.get("job_id"):
        try:
            job = await deps.call_tool(
                NODE, "marketplace", "get_job", events, job_id=state["job_id"]
            )
        except Exception as exc:  # noqa: BLE001
            events.append(obs(NODE, f"job lookup failed: {exc}"[:200]))
            job = {"title": state.get("job_id")}
    else:
        job = state.get("job") or {}
    status = "analysing" if new else "skipped"
    if not new:
        events.append(obs(NODE, "no new client messages"))
    return node_output(NODE, status, events, messages=msgs, new_messages=new, job=job)


async def classify(state: ConversationState, deps: Deps) -> dict[str, Any]:
    latest = state["new_messages"][-1]
    hits = detect_injection(latest.get("body", ""))
    intent, res = await call_structured(
        "intent_classifier",
        "liaison_intent",
        IntentClassification,
        invoke=deps.invoke,
        job_title=(state.get("job") or {}).get("title", ""),
        history=_history(state.get("messages", [])[:-1]),
        message=delimit_untrusted(latest.get("body", ""), "CLIENT_MESSAGE"),
    )
    intent.injection_detected = intent.injection_detected or bool(hits)
    if intent.intent != "scam_signal" and any(
        k in latest.get("body", "").lower()
        for k in ("whatsapp", "telegram", "paypal", "outside the platform", "off platform", "zelle")
    ):
        intent.intent = "scam_signal"
    return node_output(
        NODE,
        "drafting",
        [
            llm_event("intent_classifier", "liaison_intent", res),
            obs(NODE, f"intent {intent.intent}", injection=intent.injection_detected),
        ],
        res.usage,
        intent=intent.model_dump(),
    )


async def draft_reply(state: ConversationState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    intent = state["intent"]
    latest = state["new_messages"][-1]
    slots: list[dict[str, Any]] = []
    if intent["intent"] == "interview_request":
        try:
            res = await deps.call_tool(
                NODE, "workspace", "get_free_slots", events, days=5, slot_minutes=30, max_slots=3
            )
            slots = res.get("slots", []) if isinstance(res, dict) else []
        except Exception as exc:  # noqa: BLE001
            events.append(obs(NODE, f"calendar unavailable: {exc}"[:200]))
    evidence = state.get("evidence", []) if "evidence" in state else []  # type: ignore[operator]
    prefs = state.get("user_prefs", {}) if "user_prefs" in state else {}  # type: ignore[operator]
    price = state.get("price_quote", {}) if "price_quote" in state else {}  # type: ignore[operator]
    res = await call_prompt(
        NODE,
        "liaison_reply",
        invoke=deps.invoke,
        job_title=(state.get("job") or {}).get("title", ""),
        intent=intent["intent"],
        summary=intent.get("summary", ""),
        price=f"${price.get('amount', 'as quoted')}",
        floor=f"${prefs.get('hourly_floor') or prefs.get('min_project_budget') or 'n/a'}",
        history=_history(state.get("messages", [])[:-1]),
        message=delimit_untrusted(latest.get("body", ""), "CLIENT_MESSAGE"),
        evidence="\n".join(
            f"[{e['evidence_id']}] {e.get('title')}: {(e.get('excerpt') or '')[:300]}"
            for e in evidence
        )
        or "(none)",
        slots="; ".join(f"{s['start']} to {s['end']}" for s in slots) or "(none requested)",
        style_rules="; ".join(state.get("style_rules", [])) or "none",
        policy_rules=policy.rules_for_writer("message"),
    )
    reply = ReplyDraft(
        thread_id=state["marketplace_thread_id"],
        body=res.text.strip(),
        proposed_slots=slots,
        intent=intent["intent"],
    )
    violations = check_text(reply.body, kind="message")
    blocking = [v for v in violations if v.severity == "block"]
    verdict = ComplianceVerdict(
        allowed=not blocking,
        violations=violations,
        policy_version=int(deps.config.policy_version),
        reason="; ".join(f"{v.rule_id}: {v.detail}" for v in blocking) or "no violations",
    )
    events.append(llm_event(NODE, "liaison_reply", res))
    events.append(
        obs(
            NODE,
            f"reply drafted; compliance {'ok' if verdict.allowed else 'BLOCKED'}",
            words=len(reply.body.split()),
        )
    )
    status = "awaiting_approval" if verdict.allowed else "blocked"
    return node_output(
        NODE,
        status,
        events,
        res.usage,
        reply_draft=reply.model_dump(),
        proposed_slots=slots,
        compliance_verdict=verdict.model_dump(),
        pipeline_stage=STAGE_FOR_INTENT.get(intent["intent"], "replied"),
    )


async def send(state: ConversationState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    reply = state["reply_draft"]
    key = f"msg:{state['thread_id']}:{state['new_messages'][-1].get('message_id', 'x')}"[:128]
    try:
        res = await deps.call_tool(
            NODE,
            "marketplace",
            "send_message",
            events,
            message={
                "thread_id": reply["thread_id"],
                "body": reply["body"],
                "idempotency_key": key,
                "dry_run": False,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return node_output(
            NODE,
            "needs_attention",
            [obs(NODE, f"send failed: {exc}"[:200])],
            errors=[f"send: {exc}"[:200]],
            needs_attention_reason=f"send failed: {exc}"[:200],
        )
    hold = None
    if state.get("approval", {}).get("confirmed_slot") and state.get("proposed_slots"):
        s = state["approval"]["confirmed_slot"]
        try:
            hold = await deps.call_tool(
                NODE,
                "workspace",
                "create_interview_hold",
                events,
                start=s["start"],
                end=s["end"],
                title=f"Interview: {(state.get('job') or {}).get('title', '')[:60]}",
                idempotency_key=f"hold:{key}",
                thread_id=reply["thread_id"],
            )
        except Exception as exc:  # noqa: BLE001
            events.append(obs(NODE, f"hold failed: {exc}"[:200]))
    events.append(
        TraceEvent(
            ts=time.time(),
            node=NODE,
            kind="observation",
            name="sent",
            result={
                "message_id": res.get("message_id") if isinstance(res, dict) else None,
                "hold": hold,
            },
            note="reply sent after approval",
        )
    )
    return node_output(
        NODE,
        "submitted",
        events,
        sent={
            "message_id": res.get("message_id") if isinstance(res, dict) else None,
            "hold": hold,
            "idempotent_replay": bool(res.get("idempotent_replay"))
            if isinstance(res, dict)
            else False,
        },
    )
