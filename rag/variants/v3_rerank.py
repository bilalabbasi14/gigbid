"""V3 cross-encoder reranking over hybrid candidates (precision at small k)."""

from __future__ import annotations

from typing import Any

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text
from rag.schema import Evidence
from rag.variants.v2_hybrid import HybridRRF


class CrossEncoderRerank:
    name = "v3_rerank"

    def __init__(self, resources: Resources, base: Any | None = None) -> None:
        self.res = resources
        self.base = base or HybridRRF(
            resources, candidate_k=int(settings.config().rag.get("rerank_top_n", 20))
        )

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        top_n = int(settings.config().rag.get("rerank_top_n", 20))
        cands = self.base.retrieve(job, persona, k=top_n, filters=filters)
        if not cands:
            return []
        query = job_query_text(job)[:2000]
        scores = embeddings.rerank_scores(query, [f"{e.title}. {e.excerpt}" for e in cands])
        order = sorted(range(len(cands)), key=lambda i: -scores[i])
        out = []
        for i in order[:k]:
            e = cands[i]
            e.scores = {**e.scores, "rerank": round(float(scores[i]), 4)}
            e.score = round(float(scores[i]), 4)
            out.append(e)
        return out
