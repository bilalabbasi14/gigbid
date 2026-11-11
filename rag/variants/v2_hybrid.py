"""V2 hybrid: BM25 + dense, fused with reciprocal rank fusion. Catches exact tool and library
names ("Celery", "dbt", "Pinecone") that embeddings blur."""

from __future__ import annotations

from typing import Any

from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Evidence
from rag.variants._fusion import rrf


class HybridRRF:
    name = "v2_hybrid"

    def __init__(self, resources: Resources, candidate_k: int = 20) -> None:
        self.res = resources
        self.candidate_k = candidate_k

    def candidates(
        self, query_text: str, persona: str, filters: dict[str, Any] | None
    ) -> list[tuple[Chunk, float]]:
        dense = self.res.store.dense_search(
            embeddings.embed_query(query_text), persona, k=self.candidate_k, filters=filters
        )
        sparse = self.res.bm25(persona).search(
            query_text, k=self.candidate_k, doc_types=(filters or {}).get("doc_types")
        )
        fused = rrf([dense, sparse])
        dense_s = {c.chunk_id: s for c, s in dense}
        sparse_s = {c.chunk_id: s for c, s in sparse}
        return [(c, s) for c, s in fused], dense_s, sparse_s  # type: ignore[return-value]

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        fused, dense_s, sparse_s = self.candidates(job_query_text(job), persona, filters)  # type: ignore[misc]
        return [
            to_evidence(
                c,
                s,
                {
                    "rrf": s,
                    "dense": dense_s.get(c.chunk_id, 0.0),
                    "bm25": sparse_s.get(c.chunk_id, 0.0),
                },
            )
            for c, s in fused[:k]
        ]
