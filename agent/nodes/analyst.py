"""Job Analyst: structured JobSpec from the job post. No tools."""

from __future__ import annotations

from typing import Any

from agent.deps import Deps
from agent.handoffs import JobSpec
from agent.nodes._common import fmt_money, job_text, llm_event, node_output
from agent.state import BidState
from agent.structured import call_structured

NODE = "analyst"


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    job = state["job"]
    spec, res = await call_structured(
        NODE,
        "analyst",
        JobSpec,
        invoke=deps.invoke,
        job_id=job.get("job_id", ""),
        title=job.get("title", ""),
        payment_type=job.get("payment_type", "unknown"),
        budget=fmt_money(job.get("budget")),
        hourly_min=fmt_money(job.get("hourly_min")),
        hourly_max=fmt_money(job.get("hourly_max")),
        skills=", ".join(job.get("skills") or []) or "none listed",
        screening_questions="; ".join(job.get("screening_questions") or []) or "none",
        job_text=job_text(job),
    )
    spec.job_id = job.get("job_id", spec.job_id)
    if not spec.screening_questions and job.get("screening_questions"):
        spec.screening_questions = list(job["screening_questions"])
    if spec.budget_type == "unknown" and job.get("payment_type") in ("fixed", "hourly"):
        spec.budget_type = job["payment_type"]
    return node_output(
        NODE, None, [llm_event(NODE, "analyst", res)], res.usage, job_spec=spec.model_dump()
    )
