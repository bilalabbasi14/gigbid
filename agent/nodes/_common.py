"""Helpers shared by nodes: trace events, usage accounting, job text formatting."""

from __future__ import annotations

import time
from typing import Any

from agent.guardrails import delimit_untrusted
from agent.state import TraceEvent
from agent.structured import LLMResult


def llm_event(node: str, prompt: str, res: LLMResult, note: str = "") -> TraceEvent:
    return TraceEvent(
        ts=time.time(),
        node=node,
        kind="llm",
        name=prompt,
        args={"model": res.model},
        result={"usage": res.usage, "chars": len(res.text)},
        note=note,
        duration_ms=res.duration_ms,
    )


def obs(node: str, note: str, **result: Any) -> TraceEvent:
    return TraceEvent(
        ts=time.time(), node=node, kind="observation", name=node, result=result, note=note
    )


def job_text(job: dict[str, Any]) -> str:
    return delimit_untrusted(job.get("description", ""), "JOB_TEXT")


def fmt_money(v: Any) -> str:
    return "n/a" if v in (None, "", 0) else f"${float(v):g}"


def node_output(
    node: str,
    status: str | None,
    events: list[TraceEvent],
    usage: dict[str, int] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"trace": events, "steps": 1, **fields}
    if status:
        out["status"] = status
    if usage:
        out["usage"] = usage
    return out
