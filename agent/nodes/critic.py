"""Critic: grounding, personalisation and length check; sends the draft back at most
`budgets.max_revisions` times."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent.deps import Deps
from agent.handoffs import Critique
from agent.nodes._common import llm_event, node_output, obs
from agent.nodes.writer import evidence_block
from agent.state import BidState
from agent.structured import call_structured

NODE = "critic"
GENERIC = (
    "i am a passionate",
    "i'm a passionate",
    "dear sir",
    "dear hiring manager",
    "i hope this message finds you",
    "i have read your job",
    "i am writing to express",
)


class _Out(BaseModel):
    passed: bool = False
    grounding_score: float = 0.0
    personalisation_score: float = 0.0
    length_ok: bool = True
    issues: list[str] = Field(default_factory=list)
    revision_instructions: str = ""


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    draft, spec, job = state["proposal_draft"], state.get("job_spec", {}), state["job"]
    rnd = int(state.get("revision_count", 0))
    max_rev = int(deps.config.budgets.get("max_revisions", 2))
    text = draft["cover_letter"] + (
        "\n\nScreening answers:\n"
        + "\n".join(f"Q{i + 1}: {a}" for i, a in enumerate(draft.get("screening_answers", [])))
        if draft.get("screening_answers")
        else ""
    )
    out, res = await call_structured(
        NODE,
        "critic",
        _Out,
        invoke=deps.invoke,
        title=job.get("title", ""),
        spec_summary=spec.get("summary", ""),
        deliverables="; ".join(spec.get("deliverables", [])),
        evidence=evidence_block(state.get("evidence", []))[:6000],
        verification=str(draft.get("verification", {})),
        round=rnd,
        proposal=text,
    )
    words = int(draft.get("word_count") or len(draft["cover_letter"].split()))
    length_ok = out.length_ok and 120 <= words <= 260
    generic = any(
        draft["cover_letter"].lower().lstrip().startswith(g)
        or g in draft["cover_letter"].lower()[:160]
        for g in GENERIC
    )
    issues = list(out.issues)
    if not length_ok:
        issues.append(f"cover letter is {words} words (target 140-220)")
    if generic:
        issues.append("generic opening")
    unsupported_after = float(draft.get("verification", {}).get("unsupported_rate_after", 0.0))
    passed = (
        bool(out.passed)
        and length_ok
        and not generic
        and out.grounding_score >= 0.8
        and out.personalisation_score >= 0.7
        and unsupported_after == 0.0
    )
    critique = Critique(
        passed=passed,
        grounding_score=max(0.0, min(1.0, out.grounding_score)),
        personalisation_score=max(0.0, min(1.0, out.personalisation_score)),
        length_ok=length_ok,
        issues=issues,
        revision_instructions=out.revision_instructions,
        round=rnd,
    )
    if not passed and rnd >= max_rev:
        # loop limit reached: proceed with the best we have, visibly
        critique.issues.append(
            f"revision limit ({max_rev}) reached; proceeding to compliance with open issues"
        )
        status, next_rev = "compliance", rnd
    elif passed:
        status, next_rev = "compliance", rnd
    else:
        status, next_rev = "drafting", rnd + 1
    events = [
        llm_event(NODE, "critic", res),
        obs(NODE, "critique", passed=passed, round=rnd, next=status),
    ]
    return node_output(
        NODE, status, events, res.usage, critique=critique.model_dump(), revision_count=next_rev
    )
