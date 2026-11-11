"""V0 baseline: fixed-size chunks, one dense query built from the whole job post, top-k cosine."""

from __future__ import annotations

from typing import Any

from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Evidence


class NaiveDense:
    name = "v0_naive"

    def __init__(self, resources: Resources) -> None:
        self.res = resources

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        q = embeddings.embed_query(job_query_text(job))
        hits = self.res.store.dense_search(q, persona, k=k, filters=filters)
        return [to_evidence(c, s, {"dense": s}) for c, s in hits]
