"""V5 multi-vector projects: summary (case study), README and code chunks are indexed separately
already; here they are retrieved separately and returned as one project, so a repo whose README
looks irrelevant can still surface through its code. The returned evidence is the best chunk per
project with the project-level score (max over views, with a small bonus per extra view)."""

from __future__ import annotations

from typing import Any

from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Evidence

VIEWS = (("case_study", 1.0), ("readme", 0.9), ("code", 0.85), ("manifest", 0.6), ("review", 0.7))


class MultiVectorProjects:
    name = "v5_multivector"

    def __init__(self, resources: Resources, per_view_k: int = 8) -> None:
        self.res = resources
        self.per_view_k = per_view_k

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        q = embeddings.embed_query(job_query_text(job))
        by_project: dict[str, dict[str, Any]] = {}
        loose: list[tuple[Chunk, float]] = []
        for view, weight in VIEWS:
            f = {**(filters or {}), "doc_types": [view]}
            for c, s in self.res.store.dense_search(q, persona, k=self.per_view_k, filters=f):
                if not c.project_id:
                    loose.append((c, s * weight))
                    continue
                p = by_project.setdefault(c.project_id, {"views": {}, "best": (c, s * weight)})
                p["views"][view] = max(p["views"].get(view, 0.0), s * weight)
                if s * weight > p["best"][1]:
                    p["best"] = (c, s * weight)
        ranked = []
        for p in by_project.values():
            views = p["views"]
            score = max(views.values()) + 0.03 * (len(views) - 1)
            c, _ = p["best"]
            ranked.append((c, score, views))
        ranked.sort(key=lambda t: -t[1])
        out = [
            to_evidence(c, s, {f"view_{v}": round(x, 4) for v, x in views.items()})
            for c, s, views in ranked[:k]
        ]
        if len(out) < k:
            for c, s in sorted(loose, key=lambda t: -t[1])[: k - len(out)]:
                out.append(to_evidence(c, s, {"dense": s}))
        return out
