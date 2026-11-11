"""The bid graph (C1): one thread per job.

    scout -> [analyst | risk_assessor | fit_matcher] (parallel, Send) -> decision
      -> skip / watch -> END
      -> bid -> pricing -> writer -> verifier -> critic -(revise, max N)-> writer
                                                      -> compliance -> block -> END
                                                                    -> approval_prepare -> approval (interrupt)
                                                                         approve -> submit -> END
                                                                         edit    -> compliance (re-check) -> approval ...
                                                                         reject  -> END

Budgets: `recursion_limit` from budgets.max_graph_steps; a token budget check before every LLM
node moves the thread to needs_attention. Retries and timeouts per node come from config too.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from agent import settings
from agent.deps import Deps
from agent.nodes import (
    analyst,
    approval,
    compliance,
    critic,
    decision,
    fit_matcher,
    pricing,
    risk_assessor,
    scout,
    verifier,
    writer,
)
from agent.state import BidState

NodeFn = Callable[[BidState, Deps], Awaitable[dict[str, Any]]]


def _guarded(
    name: str, fn: NodeFn, deps: Deps, llm_node: bool
) -> Callable[[BidState], Awaitable[dict[str, Any]]]:
    """Wrap a node: token-budget check, error capture into state (dead-letter instead of crash)."""

    async def node(state: BidState) -> dict[str, Any]:
        budget = int(deps.config.budgets.get("max_tokens_per_thread", 40000))
        used = sum((state.get("usage") or {}).values())
        if llm_node and used >= budget:
            return {
                "status": "needs_attention",
                "needs_attention_reason": f"token budget {budget} exhausted before {name} (used {used})",
                "errors": [f"{name}: token budget exhausted"],
                "steps": 1,
            }
        try:
            return await fn(state, deps)
        except Exception as exc:  # noqa: BLE001 - dead-letter the thread with the reason visible
            return {
                "status": "needs_attention",
                "needs_attention_reason": f"{name} failed: {exc}"[:300],
                "errors": [f"{name}: {exc}"[:300]],
                "steps": 1,
            }

    node.__name__ = name
    return node


def fan_out(state: BidState) -> list[Send] | str:
    if state.get("status") in ("skipped", "needs_attention"):  # scout found a duplicate or failed
        return END
    return [Send("analyst", state), Send("risk_assessor", state), Send("fit_matcher", state)]


def after_decision(state: BidState) -> Literal["pricing", "__end__"]:
    if state.get("status") == "needs_attention":
        return END
    return "pricing" if state.get("decision", {}).get("decision") == "bid" else END


def after_pricing(state: BidState) -> Literal["writer", "__end__"]:
    return "writer" if state.get("status") == "drafting" else END


def after_critic(state: BidState) -> Literal["writer", "compliance", "__end__"]:
    s = state.get("status")
    if s == "drafting":
        return "writer"
    if s == "compliance":
        return "compliance"
    return END


def after_compliance(state: BidState) -> Literal["approval_prepare", "__end__"]:
    return "approval_prepare" if state.get("status") == "awaiting_approval" else END


def after_approval(state: BidState) -> Literal["submit", "compliance", "__end__"]:
    s = state.get("status")
    if s == "submitting":
        return "submit"
    if s == "compliance":
        return "compliance"
    return END


def _needs_attention_guard(nxt: str):  # type: ignore[no-untyped-def]
    def route(state: BidState) -> str:
        return END if state.get("status") == "needs_attention" else nxt

    return route


def build_bid_graph(
    deps: Deps | None = None, checkpointer: BaseCheckpointSaver | None = None, *, store: Any = None
):  # type: ignore[no-untyped-def]
    deps = deps or Deps()
    cfg = settings.config().budgets
    retry = RetryPolicy(
        max_attempts=int(cfg.get("per_node_retries", 2)) + 1,
        initial_interval=1.0,
        backoff_factor=2.0,
    )
    timeout = float(cfg.get("per_node_timeout_seconds", 90))

    g = StateGraph(BidState)
    nodes: list[tuple[str, NodeFn, bool]] = [
        ("scout", scout.run, False),
        ("analyst", analyst.run, True),
        ("risk_assessor", risk_assessor.run, True),
        ("fit_matcher", fit_matcher.run, True),
        ("decision", decision.run, False),
        ("pricing", pricing.run, False),
        ("writer", writer.run, True),
        ("verifier", verifier.run, True),
        ("critic", critic.run, True),
        ("compliance", compliance.run, True),
        ("approval_prepare", approval.prepare, False),
        ("submit", approval.submit, False),
    ]
    for name, fn, is_llm in nodes:
        g.add_node(name, _guarded(name, fn, deps, is_llm), retry_policy=retry, timeout=timeout)

    # the interrupt node is NOT wrapped: exceptions must not swallow GraphInterrupt
    async def approval_node(state: BidState) -> dict[str, Any]:
        return await approval.wait_for_human(state, deps)

    g.add_node("approval", approval_node)

    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", fan_out, ["analyst", "risk_assessor", "fit_matcher", END])
    for n in ("analyst", "risk_assessor", "fit_matcher"):
        g.add_edge(n, "decision")
    g.add_conditional_edges("decision", after_decision, {"pricing": "pricing", END: END})
    g.add_conditional_edges("pricing", after_pricing, {"writer": "writer", END: END})
    g.add_conditional_edges(
        "writer", _needs_attention_guard("verifier"), {"verifier": "verifier", END: END}
    )
    g.add_conditional_edges(
        "verifier", _needs_attention_guard("critic"), {"critic": "critic", END: END}
    )
    g.add_conditional_edges(
        "critic", after_critic, {"writer": "writer", "compliance": "compliance", END: END}
    )
    g.add_conditional_edges(
        "compliance", after_compliance, {"approval_prepare": "approval_prepare", END: END}
    )
    g.add_conditional_edges(
        "approval_prepare", _needs_attention_guard("approval"), {"approval": "approval", END: END}
    )
    g.add_conditional_edges(
        "approval", after_approval, {"submit": "submit", "compliance": "compliance", END: END}
    )
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store)


def run_config(
    thread_id: str, *, user_id: str = "local", recursion_limit: int | None = None
) -> dict[str, Any]:
    limit = recursion_limit or int(settings.config().budgets.get("max_graph_steps", 40))
    return {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "recursion_limit": limit,
        "tags": ["bid_graph"],
        "metadata": {"thread_id": thread_id, "user_id": user_id},
    }


def initial_state(
    job_id: str,
    *,
    thread_id: str,
    user_id: str = "local",
    persona: str = "ai_ml",
    user_prefs: dict[str, Any] | None = None,
    job: dict[str, Any] | None = None,
    style_rules: list[str] | None = None,
    outcome_hints: list[str] | None = None,
) -> BidState:
    st: BidState = {
        "thread_id": thread_id,
        "user_id": user_id,
        "persona": persona,
        "job_id": job_id,
        "status": "queued",
        "user_prefs": user_prefs or {},
        "style_rules": style_rules or [],
        "outcome_hints": outcome_hints or [],
        "revision_count": 0,
        "errors": [],
        "trace": [],
        "usage": {},
        "steps": 0,
    }
    if job:
        st["job"] = job
    return st
