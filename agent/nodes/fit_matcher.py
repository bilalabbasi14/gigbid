"""Fit Matcher: extract requirements, search portfolio evidence per requirement (Portfolio MCP),
and build the requirement -> evidence matrix with a fit score."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent.deps import Deps
from agent.handoffs import EvidenceRef, FitReport, RequirementMatch
from agent.nodes._common import job_text, llm_event, node_output, obs
from agent.state import BidState, TraceEvent
from agent.structured import call_structured

NODE = "fit_matcher"


class _Reqs(BaseModel):
    requirements: list[str] = Field(default_factory=list)


class _Row(BaseModel):
    requirement: str
    strength: str = "none"
    note: str = ""


class _Assess(BaseModel):
    matrix: list[_Row] = Field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


def _ref(item: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=item["evidence_id"],
        title=item.get("title", ""),
        type=item.get("type", ""),
        project_id=item.get("project_id"),
        excerpt=(item.get("excerpt") or "")[:500],
        source=item.get("source", ""),
        year=item.get("date"),
        outcome=item.get("outcome"),
        score=float(item.get("score") or 0),
    )


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    events: list[TraceEvent] = []
    job = state["job"]
    persona = state.get("persona", "ai_ml")
    usage: dict[str, int] = {}

    reqs, res = await call_structured(
        NODE,
        "fit_requirements",
        _Reqs,
        invoke=deps.invoke,
        title=job.get("title", ""),
        skills=", ".join(job.get("skills") or []) or "none",
        job_text=job_text(job),
    )
    events.append(llm_event(NODE, "fit_requirements", res))
    usage = {k: usage.get(k, 0) + v for k, v in res.usage.items()}
    requirements = [r for r in reqs.requirements if r.strip()][:6] or [job.get("title", "the job")]

    k = int(deps.config.rag.get("k", 5))
    matrix: list[RequirementMatch] = []
    for r in requirements:
        try:
            found = await deps.call_tool(
                NODE, "portfolio", "search_evidence", events, requirement=r, k=k, persona=persona
            )
            items = found.get("items", []) if isinstance(found, dict) else []
        except Exception as exc:  # noqa: BLE001
            events.append(obs(NODE, f"evidence search failed for {r[:40]!r}: {exc}"[:300]))
            items = []
        # drop past proposals written for this very job (they are not evidence of ability)
        items = [
            i
            for i in items
            if not (i.get("type") == "proposal" and i.get("job_id") == job.get("job_id"))
        ]
        matrix.append(RequirementMatch(requirement=r, evidence=[_ref(i) for i in items[:3]]))

    block = "\n".join(
        f"- {m.requirement}\n"
        + (
            "\n".join(
                f"    [{e.evidence_id}] ({e.type}, {e.year}) {e.title}: {e.excerpt[:220]}"
                for e in m.evidence
            )
            or "    (no evidence found)"
        )
        for m in matrix
    )
    try:
        assess, res2 = await call_structured(
            NODE,
            "fit_assess",
            _Assess,
            invoke=deps.invoke,
            title=job.get("title", ""),
            matrix=block,
        )
        events.append(llm_event(NODE, "fit_assess", res2))
        usage = {k_: usage.get(k_, 0) + v for k_, v in res2.usage.items()}
        by_req = {a.requirement.strip().lower(): a for a in assess.matrix}
        for m in matrix:
            a = by_req.get(m.requirement.strip().lower())
            if a and a.strength in ("strong", "partial", "none"):
                m.strength, m.note = a.strength, a.note  # type: ignore[assignment]
            elif not m.evidence:
                m.strength = "none"
        score = max(0.0, min(1.0, assess.score))
        reasons, matched, missing = assess.reasons[:4], assess.matched_skills, assess.missing_skills
    except Exception as exc:  # noqa: BLE001 - heuristic fallback from retrieval scores
        events.append(
            obs(NODE, f"fit assessment model unavailable, using retrieval scores: {exc}"[:300])
        )
        for m in matrix:
            top = max((e.score for e in m.evidence), default=0.0)
            m.strength = "strong" if top >= 0.75 else "partial" if top >= 0.55 else "none"  # type: ignore[assignment]
        weights = [1.0 / (i + 1) for i in range(len(matrix))]
        vals = {"strong": 1.0, "partial": 0.5, "none": 0.0}
        score = sum(w * vals[m.strength] for w, m in zip(weights, matrix, strict=True)) / sum(
            weights
        )
        reasons, matched, missing = ["heuristic fit from retrieval scores"], [], []

    evidence_ids = sorted({e.evidence_id for m in matrix for e in m.evidence})
    report = FitReport(
        score=round(score, 3),
        matrix=matrix,
        matched_skills=matched,
        missing_skills=missing,
        evidence_ids=evidence_ids,
        reasons=reasons,
    )
    events.append(
        obs(
            NODE,
            "fit matrix built",
            score=report.score,
            requirements=len(matrix),
            evidence=len(evidence_ids),
        )
    )
    evidence = [e.model_dump() for m in matrix for e in m.evidence]
    seen: set[str] = set()
    evidence = [e for e in evidence if not (e["evidence_id"] in seen or seen.add(e["evidence_id"]))]  # type: ignore[func-returns-value]
    return node_output(NODE, None, events, usage, fit_report=report.model_dump(), evidence=evidence)


def _json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
