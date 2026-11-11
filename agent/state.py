"""Graph state (C2). Three things are kept apart:

* **State** (this file): what the job or conversation needs right now. Typed, one field per
  artefact, reducers only where parallel branches write.
* **Execution trace**: every tool name, argument, result and observation. Stored under `trace`
  with an append reducer so it survives checkpoints, but nothing reads it to decide; it exists
  for audit, the run viewer and debugging. Also mirrored to the MCP audit log.
* **Long-term memory**: never in state. Promotion rules in agent/memory write to the LangGraph
  store; nodes only read `style_rules` / `outcome_hints` snapshots that the graph loads at start.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

RunStatus = Literal[
    "queued",
    "analysing",
    "decided",
    "pricing",
    "drafting",
    "verifying",
    "critiquing",
    "compliance",
    "awaiting_approval",
    "submitting",
    "submitted",
    "skipped",
    "watch",
    "rejected",
    "blocked",
    "needs_attention",
    "failed",
]


def _merge_usage(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + int(v)
    return out


def _last(a: Any, b: Any) -> Any:
    return b if b is not None else a


class TraceEvent(TypedDict, total=False):
    ts: float
    node: str
    kind: Literal["tool_call", "tool_result", "llm", "observation", "error", "interrupt", "resume"]
    name: str
    args: dict[str, Any]
    result: Any
    note: str
    duration_ms: int


class BidState(TypedDict, total=False):
    # identity
    thread_id: str
    user_id: str
    persona: str
    job_id: str
    status: RunStatus
    # inputs
    job: dict[str, Any]
    user_prefs: dict[str, Any]  # rates floor, filters, weekly connects budget, autonomy
    style_rules: list[str]  # snapshot from style memory (read-only here)
    outcome_hints: list[str]  # snapshot from outcome memory (read-only here)
    # parallel analyses (each written by exactly one branch)
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    # decision and pricing
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    # drafting loop
    evidence: list[dict[str, Any]]
    proposal_draft: dict[str, Any]
    critique: dict[str, Any]
    revision_count: int
    compliance_verdict: dict[str, Any]
    # approval and outcome
    approval_payload: dict[str, Any]
    approval: dict[str, Any]
    edit_diff: dict[str, Any]
    submission: dict[str, Any]
    outcome: dict[str, Any]
    # bookkeeping with reducers (parallel-safe)
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    usage: Annotated[dict[str, int], _merge_usage]
    steps: Annotated[int, operator.add]
    needs_attention_reason: str


class ConversationState(TypedDict, total=False):
    thread_id: str
    user_id: str
    persona: str
    marketplace_thread_id: str
    job_id: str
    job: dict[str, Any]
    messages: list[dict[str, Any]]
    new_messages: list[dict[str, Any]]
    intent: dict[str, Any]
    reply_draft: dict[str, Any]
    proposed_slots: list[dict[str, Any]]
    compliance_verdict: dict[str, Any]
    approval: dict[str, Any]
    sent: dict[str, Any]
    pipeline_stage: str
    status: RunStatus
    style_rules: list[str]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    usage: Annotated[dict[str, int], _merge_usage]
    steps: Annotated[int, operator.add]
    needs_attention_reason: str
