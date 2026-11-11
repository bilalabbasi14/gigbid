"""V9 skill graph (GraphRAG over the portfolio's structure).

Nodes: skills/libraries, projects, client industries, outcomes. Edges come from project metadata
(projects.json), case-study front matter, repository manifests and the outcomes of past
proposals that cited each project. A job is mapped onto skill nodes (exact and alias matches on
its title, listed skills and text) plus an industry node; projects are scored by the weighted
skills they connect to, an industry match and their best proposal outcome, then the best chunk of
each top project is returned as evidence. Answers questions like "have I done X for a client in
industry Y" that similarity search cannot. Deterministic: no LLM calls.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Evidence

ALIASES = {
    "llm": ["large language model", "gpt", "openai", "llama"],
    "rag": ["retrieval augmented", "retrieval-augmented", "vector search", "semantic search"],
    "pytorch": ["torch"],
    "scikit-learn": ["sklearn", "scikit"],
    "power bi": ["powerbi", "dax"],
    "next.js": ["nextjs", "next js"],
    "react": ["react.js", "reactjs"],
    "node.js": ["node", "nodejs", "express"],
    "postgresql": ["postgres", "psql"],
    "computer vision": ["opencv", "image", "yolo", "object detection"],
    "nlp": ["natural language", "text classification", "spacy", "transformers"],
    "dashboard": ["dashboards", "reporting", "kpi"],
    "etl": ["pipeline", "data pipeline", "airflow", "dbt"],
}
OUTCOME_W = {"won": 0.3, "replied": 0.15, "ignored": 0.0}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


class SkillGraph:
    name = "v9_skill_graph"

    def __init__(self, resources: Resources) -> None:
        self.res = resources
        self._graphs: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ graph build
    def graph(self, persona: str) -> dict[str, Any]:
        if persona in self._graphs:
            return self._graphs[persona]
        proj_path = settings.ROOT / "data/personas" / persona / "projects.json"
        projects = (
            {p["id"]: p for p in json.loads(proj_path.read_text(encoding="utf-8"))}
            if proj_path.exists()
            else {}
        )
        skill_to_projects: dict[str, set[str]] = defaultdict(set)
        project_industry: dict[str, str] = {}
        project_outcome: dict[str, str] = {}
        chunks_by_project: dict[str, list[Chunk]] = defaultdict(list)
        for c in self.res.store.all_chunks(persona):
            if not c.project_id:
                continue
            chunks_by_project[c.project_id].append(c)
            for s in c.skills + c.libraries:
                skill_to_projects[_norm(s)].add(c.project_id)
            if c.client_industry:
                project_industry[c.project_id] = _norm(c.client_industry)
            if (
                c.doc_type == "proposal"
                and c.outcome
                and OUTCOME_W.get(c.outcome, 0)
                > OUTCOME_W.get(project_outcome.get(c.project_id, "ignored"), 0)
            ):
                project_outcome[c.project_id] = c.outcome
        for pid, p in projects.items():
            for s in p.get("skills", []) + p.get("libraries", []):
                skill_to_projects[_norm(s)].add(pid)
            if p.get("client_industry"):
                project_industry[pid] = _norm(p["client_industry"])
        n_projects = max(1, len(set(chunks_by_project) | set(projects)))
        idf = {s: math.log(1 + n_projects / len(ps)) for s, ps in skill_to_projects.items() if ps}
        g = {
            "skills": skill_to_projects,
            "idf": idf,
            "industry": project_industry,
            "outcome": project_outcome,
            "chunks": chunks_by_project,
            "projects": projects,
        }
        self._graphs[persona] = g
        return g

    # ------------------------------------------------------------ query mapping
    def job_skills(self, job: dict[str, Any], g: dict[str, Any]) -> dict[str, float]:
        text = _norm(
            " ".join(
                [
                    job.get("title", ""),
                    " ".join(job.get("skills") or []),
                    job.get("description", "")[:3000],
                ]
            )
        )
        listed = {_norm(s) for s in job.get("skills") or []}
        hits: dict[str, float] = {}
        for skill in g["skills"]:
            variants = [skill, *ALIASES.get(skill, [])]
            if any(
                re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", text)
                for v in variants
                if len(v) > 1
            ):
                hits[skill] = g["idf"].get(skill, 1.0) * (1.5 if skill in listed else 1.0)
        return hits

    def job_industry(self, job: dict[str, Any], g: dict[str, Any]) -> str | None:
        text = _norm(job.get("title", "") + " " + job.get("description", "")[:2000])
        for ind in set(g["industry"].values()):
            if ind and re.search(rf"\b{re.escape(ind.split()[0])}", text):
                return ind
        return None

    # ------------------------------------------------------------ retrieval
    def score_projects(
        self, job: dict[str, Any], persona: str
    ) -> list[tuple[str, float, dict[str, float]]]:
        g = self.graph(persona)
        skills = self.job_skills(job, g)
        industry = self.job_industry(job, g)
        total = sum(skills.values()) or 1.0
        scores: dict[str, dict[str, float]] = defaultdict(
            lambda: {"skills": 0.0, "industry": 0.0, "outcome": 0.0}
        )
        for s, w in skills.items():
            for pid in g["skills"][s]:
                scores[pid]["skills"] += w / total
        for pid in list(scores) + (
            [p for p, ind in g["industry"].items() if industry and ind == industry]
        ):
            if industry and g["industry"].get(pid) == industry:
                scores[pid]["industry"] = 0.2
            scores[pid]["outcome"] = OUTCOME_W.get(g["outcome"].get(pid, ""), 0.0)
        ranked = [
            (pid, parts["skills"] + parts["industry"] + parts["outcome"], dict(parts))
            for pid, parts in scores.items()
        ]
        return sorted(ranked, key=lambda t: -t[1])

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        g = self.graph(persona)
        ranked = self.score_projects(job, persona)
        if not ranked:
            hits = self.res.store.dense_search(
                embeddings.embed_query(job_query_text(job)), persona, k=k, filters=filters
            )
            return [to_evidence(c, s, {"dense": s, "graph": 0.0}) for c, s in hits]
        qv = embeddings.embed_query(job_query_text(job))
        out: list[Evidence] = []
        for pid, score, parts in ranked[:k]:
            chunks = [c for c in g["chunks"].get(pid, []) if c.doc_type != "proposal"] or g[
                "chunks"
            ].get(pid, [])
            if not chunks:
                continue
            # the project's chunk closest to the job (stored embeddings, one indexed query)
            near = self.res.store.dense_search(qv, persona, k=3, filters={"project_id": pid})
            near = [(c, sc) for c, sc in near if c.doc_type != "proposal"] or near
            best = near[0][0] if near else chunks[0]
            out.append(
                to_evidence(
                    best,
                    round(score, 4),
                    {
                        "graph": round(score, 4),
                        **{f"graph_{k_}": round(v, 4) for k_, v in parts.items()},
                    },
                )
            )
        return out

    def explain(self, job: dict[str, Any], persona: str) -> dict[str, Any]:
        """For the UI and the report: which skills and industry the job mapped to."""
        g = self.graph(persona)
        return {
            "skills": self.job_skills(job, g),
            "industry": self.job_industry(job, g),
            "top_projects": self.score_projects(job, persona)[:5],
        }
