"""Scout: fetch the job through the marketplace MCP server and de-duplicate against jobs already
seen for this user (title + description fingerprint). The scheduled search lives in the worker;
this node handles one job handed in by job_id."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from agent.deps import Deps
from agent.nodes._common import node_output, obs
from agent.state import BidState, TraceEvent

NODE = "scout"


def fingerprint(job: dict[str, Any]) -> str:
    key = re.sub(r"\W+", " ", f"{job.get('title', '')} {job.get('description', '')[:300]}".lower())
    key = re.sub(r"^(reposted|urgent|re)\s*", "", key.strip())
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]


async def run(state: BidState, deps: Deps, seen: set[str] | None = None) -> dict[str, Any]:
    events: list[TraceEvent] = []
    job = state.get("job")
    if not job:
        job = await deps.call_tool(NODE, "marketplace", "get_job", events, job_id=state["job_id"])
    fp = fingerprint(job)
    job = {**job, "fingerprint": fp}
    if seen is not None and fp in seen:
        events.append(obs(NODE, "duplicate of a job already analysed; skipping", fingerprint=fp))
        return node_output(
            NODE,
            "skipped",
            events,
            job=job,
            decision={
                "decision": "skip",
                "reasons": ["duplicate of a job already analysed"],
                "fit_score": 0.0,
                "risk_score": 0.0,
                "auto": True,
            },
        )
    events.append(
        TraceEvent(
            ts=time.time(),
            node=NODE,
            kind="observation",
            name="job_received",
            result={"job_id": job.get("job_id"), "title": job.get("title"), "fingerprint": fp},
            note="job queued for parallel analysis",
        )
    )
    return node_output(
        NODE, "analysing", events, job=job, job_id=job.get("job_id", state.get("job_id"))
    )
