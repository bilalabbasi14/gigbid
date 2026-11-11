"""Portfolio tool implementations (pure functions over the chunk store + retriever)."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent import settings
from rag.retriever import Resources, build_retriever
from rag.schema import Evidence

PERSONAS_ROOT = settings.ROOT / "data/personas"
DocTypeFilter = Literal["cv", "case_study", "readme", "code", "review", "proposal", "manifest"]


class SearchFilters(BaseModel):
    doc_types: list[DocTypeFilter] | None = Field(
        default=None, description="Restrict to these evidence types"
    )
    outcome: Literal["won", "replied", "ignored"] | None = Field(
        default=None, description="Past proposals only: outcome"
    )
    min_year: int | None = Field(default=None, ge=2000, le=2100)
    project_id: str | None = Field(default=None, description="Restrict to one project, e.g. p03")


class EvidenceItem(BaseModel):
    evidence_id: str
    type: str
    title: str
    project_id: str | None
    excerpt: str
    source: str
    date: int | None
    outcome: str | None
    skills: list[str]
    score: float
    scores: dict[str, float]


class SearchEvidenceResult(BaseModel):
    requirement: str
    persona: str
    variant: str
    items: list[EvidenceItem]


class CaseStudy(BaseModel):
    project_id: str
    persona: str
    name: str
    year: int | None
    client_industry: str | None
    skills: list[str]
    libraries: list[str]
    outcome_metrics: list[str]
    case_study_markdown: str | None
    readme_markdown: str | None
    code_files: list[str]
    reviews: list[dict[str, Any]]
    proposals_citing: list[str]


class SkillEntry(BaseModel):
    skill: str
    projects: list[str]
    evidence_count: int
    last_used_year: int | None
    won_proposals: int


class PortfolioService:
    """Holds the shared retriever resources; one instance per server process."""

    def __init__(self, resources: Resources | None = None, variant: str | None = None) -> None:
        self.res = resources or Resources()
        self.variant = variant or settings.config().rag.get("variant", "v0_naive")
        self._retriever = None

    @property
    def retriever(self):  # type: ignore[no-untyped-def]
        if self._retriever is None:
            self._retriever = build_retriever(self.variant, self.res)
        return self._retriever

    def search_evidence(
        self, requirement: str, persona: str, k: int = 5, filters: SearchFilters | None = None
    ) -> SearchEvidenceResult:
        f = filters.model_dump(exclude_none=True) if filters else {}
        job = {"title": requirement, "description": requirement, "skills": []}
        ev: list[Evidence] = self.retriever.retrieve(job, persona, k=k, filters=f or None)
        return SearchEvidenceResult(
            requirement=requirement,
            persona=persona,
            variant=self.variant,
            items=[
                EvidenceItem(
                    evidence_id=e.evidence_id,
                    type=e.doc_type,
                    title=e.title,
                    project_id=e.project_id,
                    excerpt=e.excerpt,
                    source=e.source_path,
                    date=e.year,
                    outcome=e.outcome,
                    skills=e.skills,
                    score=e.score,
                    scores=e.scores,
                )
                for e in ev
            ],
        )

    def _projects(self, persona: str) -> list[dict[str, Any]]:
        p = PERSONAS_ROOT / persona / "projects.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def get_case_study(self, project_id: str, persona: str) -> CaseStudy | None:
        proj = next((p for p in self._projects(persona) if p["id"] == project_id), None)
        if not proj:
            return None
        chunks = self.res.store.by_project(persona, project_id)
        case = "\n\n".join(c.text for c in chunks if c.doc_type == "case_study") or None
        readme = "\n\n".join(c.text for c in chunks if c.doc_type == "readme") or None
        code_files = sorted({c.source_path for c in chunks if c.doc_type == "code"})
        reviews = [{"text": c.text, "year": c.year} for c in chunks if c.doc_type == "review"]
        citing = sorted({c.doc_id for c in chunks if c.doc_type == "proposal"})
        return CaseStudy(
            project_id=project_id,
            persona=persona,
            name=proj["name"],
            year=proj.get("year"),
            client_industry=proj.get("client_industry"),
            skills=proj.get("skills", []),
            libraries=proj.get("libraries", []),
            outcome_metrics=proj.get("outcome_metrics", []),
            case_study_markdown=case,
            readme_markdown=readme,
            code_files=code_files,
            reviews=reviews,
            proposals_citing=citing,
        )

    def list_skills(self, persona: str) -> list[SkillEntry]:
        chunks = self.res.store.all_chunks(persona)
        by_skill: dict[str, dict[str, Any]] = {}
        for c in chunks:
            for s in c.skills + c.libraries:
                key = s.strip()
                if not key:
                    continue
                d = by_skill.setdefault(key, {"projects": set(), "n": 0, "year": None, "won": 0})
                d["n"] += 1
                if c.project_id:
                    d["projects"].add(c.project_id)
                if c.year and (d["year"] is None or c.year > d["year"]):
                    d["year"] = c.year
                if c.doc_type == "proposal" and c.outcome == "won":
                    d["won"] += 1
        out = [
            SkillEntry(
                skill=k,
                projects=sorted(v["projects"]),
                evidence_count=v["n"],
                last_used_year=v["year"],
                won_proposals=v["won"],
            )
            for k, v in by_skill.items()
        ]
        return sorted(out, key=lambda e: (-e.evidence_count, e.skill))

    def get_proposal(self, doc_id: str, persona: str) -> dict[str, Any] | None:
        for c in self.res.store.all_chunks(persona):
            if c.doc_id == doc_id and c.doc_type == "proposal":
                return {
                    "doc_id": c.doc_id,
                    "title": c.title,
                    "cover_letter": c.text,
                    "outcome": c.outcome,
                    "job_id": c.job_id,
                    "year": c.year,
                    "project_id": c.project_id,
                }
        return None
