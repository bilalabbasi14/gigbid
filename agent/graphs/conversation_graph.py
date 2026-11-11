"""The conversation graph (C1): one thread per client conversation.

fetch_messages -> (none) END
               -> classify -> draft_reply -> blocked END
                                          -> approval (interrupt) -> approve -> send -> END
                                                                    -> edit    -> send (edited text, re-checked)
                                                                    -> reject  -> END
"""

from __future__ import annotations

import difflib
import time
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from agent import settings
from agent.deps import Deps
from agent.handoffs import ApprovalDecision, ComplianceVerdict
from agent.nodes import client_liaison as liaison
from agent.nodes.compliance import check_text
from agent.state import ConversationState, TraceEvent


def _guard(name: str, fn, deps: Deps):  # type: ignore[no-untyped-def]
    async def node(state: ConversationState) -> dict[str, Any]:
        try:
            return await fn(state, deps)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "needs_attention",
                "needs_attention_reason": f"{name} failed: {exc}"[:300],
                "errors": [f"{name}: {exc}"[:300]],
                "steps": 1,
            }

    node.__name__ = name
    return node


async def approval_node(state: ConversationState) -> dict[str, Any]:
    payload = {
        "kind": "message",
        "thread_id": state["thread_id"],
        "marketplace_thread_id": state["marketplace_thread_id"],
        "job": state.get("job"),
        "intent": state.get("intent"),
        "reply": state.get("reply_draft"),
        "proposed_slots": state.get("proposed_slots", []),
        "compliance": state.get("compliance_verdict"),
        "latest_message": state["new_messages"][-1] if state.get("new_messages") else None,
    }
    events = [
        TraceEvent(
            ts=time.time(),
            node="approval",
            kind="interrupt",
            name="approval",
            note="waiting for the human",
        )
    ]
    raw = interrupt(payload)
    decision = ApprovalDecision.model_validate(
        raw if isinstance(raw, dict) else {"action": str(raw)}
    )
    events.append(
        TraceEvent(
            ts=time.time(),
            node="approval",
            kind="resume",
            name="approval",
            result={"action": decision.action},
            note="human decided",
        )
    )
    out: dict[str, Any] = {
        "approval": {
            **decision.model_dump(),
            "confirmed_slot": raw.get("confirmed_slot") if isinstance(raw, dict) else None,
        },
        "trace": events,
        "steps": 1,
    }
    if decision.action == "reject":
        return {**out, "status": "rejected"}
    if decision.action == "edit" and decision.edited_cover_letter is not None:
        before = state["reply_draft"]["body"]
        after = decision.edited_cover_letter
        violations = check_text(after, kind="message")
        blocking = [v for v in violations if v.severity == "block"]
        verdict = ComplianceVerdict(
            allowed=not blocking,
            violations=violations,
            policy_version=int(settings.config().policy_version),
            reason="; ".join(f"{v.rule_id}: {v.detail}" for v in blocking) or "no violations",
        )
        out["compliance_verdict"] = verdict.model_dump()
        out["edit_diff"] = {
            "before": before,
            "after": after,
            "unified": "\n".join(
                difflib.unified_diff(
                    before.splitlines(), after.splitlines(), "agent", "user", lineterm=""
                )
            ),
            "changed": before != after,
        }
        if not verdict.allowed:
            return {**out, "status": "blocked"}
        out["reply_draft"] = {**state["reply_draft"], "body": after}
    return {**out, "status": "submitting"}


def build_conversation_graph(
    deps: Deps | None = None, checkpointer: BaseCheckpointSaver | None = None, *, store: Any = None
):  # type: ignore[no-untyped-def]
    deps = deps or Deps()
    cfg = settings.config().budgets
    retry = RetryPolicy(
        max_attempts=int(cfg.get("per_node_retries", 2)) + 1,
        initial_interval=1.0,
        backoff_factor=2.0,
    )
    timeout = float(cfg.get("per_node_timeout_seconds", 180))
    g = StateGraph(ConversationState)
    g.add_node(
        "fetch_messages",
        _guard("fetch_messages", liaison.fetch_messages, deps),
        retry_policy=retry,
        timeout=timeout,
    )
    g.add_node(
        "classify", _guard("classify", liaison.classify, deps), retry_policy=retry, timeout=timeout
    )
    g.add_node(
        "draft_reply",
        _guard("draft_reply", liaison.draft_reply, deps),
        retry_policy=retry,
        timeout=timeout,
    )
    g.add_node("approval", approval_node)
    g.add_node("send", _guard("send", liaison.send, deps), retry_policy=retry, timeout=timeout)
    g.add_edge(START, "fetch_messages")
    g.add_conditional_edges(
        "fetch_messages",
        lambda s: "classify" if s.get("status") == "analysing" else END,
        {"classify": "classify", END: END},
    )
    g.add_conditional_edges(
        "classify",
        lambda s: "draft_reply" if s.get("status") == "drafting" else END,
        {"draft_reply": "draft_reply", END: END},
    )
    g.add_conditional_edges(
        "draft_reply",
        lambda s: "approval" if s.get("status") == "awaiting_approval" else END,
        {"approval": "approval", END: END},
    )
    g.add_conditional_edges(
        "approval",
        lambda s: "send" if s.get("status") == "submitting" else END,
        {"send": "send", END: END},
    )
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store)


def initial_conversation_state(
    *,
    thread_id: str,
    marketplace_thread_id: str,
    user_id: str = "local",
    persona: str = "ai_ml",
    job_id: str | None = None,
    style_rules: list[str] | None = None,
) -> ConversationState:
    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "persona": persona,
        "marketplace_thread_id": marketplace_thread_id,
        "job_id": job_id or "",
        "messages": [],
        "new_messages": [],
        "status": "queued",
        "style_rules": style_rules or [],
        "errors": [],
        "trace": [],
        "usage": {},
        "steps": 0,
    }


def conversation_config(thread_id: str, *, user_id: str = "local") -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "recursion_limit": 20,
        "tags": ["conversation_graph"],
        "metadata": {"thread_id": thread_id, "user_id": user_id},
    }
