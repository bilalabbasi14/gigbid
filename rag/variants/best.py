"""`best`: the shipped pipeline, assembled from the components the evaluation favoured.
Composition is config-driven (rag.best.*) so the ablation can switch pieces off one at a time:

    rag:
      best:
        decompose: true      # V1 per-requirement queries
        hybrid: true         # V2 BM25 + dense (else dense only)
        rerank: true         # V3 cross-encoder
        outcome: true        # V4 boosts
        corrective: false    # V8 loop around the whole thing
"""

from __future__ import annotations

from typing import Any

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Evidence
from rag.variants._fusion import rrf
from rag.variants.v1_decompose import extract_requirements
from rag.variants.v4_outcome import OutcomeAware


class BestPipeline:
    name = "best"

    def __init__(self, resources: Resources, **overrides: Any) -> None:
        self.res = resources
        cfg = dict(settings.config().rag.get("best", {}))
        cfg.update(overrides)
        self.decompose = bool(cfg.get("decompose", True))
        self.hybrid = bool(cfg.get("hybrid", True))
        self.rerank = bool(cfg.get("rerank", True))
        self.outcome = bool(cfg.get("outcome", True))
        self.corrective = bool(cfg.get("corrective", False))
        self.candidate_k = int(cfg.get("candidate_k", 20))
        self._outcome = OutcomeAware(resources, base=self) if self.outcome else None

    def _lists_for(
        self, text: str, persona: str, filters: dict[str, Any] | None
    ) -> list[list[tuple[Chunk, float]]]:
        lists = [
            self.res.store.dense_search(
                embeddings.embed_query(text), persona, k=self.candidate_k, filters=filters
            )
        ]
        if self.hybrid:
            lists.append(
                self.res.bm25(persona).search(
                    text, k=self.candidate_k, doc_types=(filters or {}).get("doc_types")
                )
            )
        return lists

    def _candidates(
        self, job: dict[str, Any], persona: str, filters: dict[str, Any] | None
    ) -> tuple[list[tuple[Chunk, float]], dict[str, str]]:
        queries = [("", job_query_text(job))]
        if self.decompose:
            queries += [(r, r) for r in extract_requirements(job)]
        lists: list[list[tuple[Chunk, float]]] = []
        req_of: dict[str, str] = {}
        for req, text in queries:
            for lst in self._lists_for(text, persona, filters):
                lists.append(lst)
                for c, _ in lst:
                    if req:
                        req_of.setdefault(c.chunk_id, req)
        return rrf(lists), req_of

    def _core(
        self, job: dict[str, Any], persona: str, k: int, filters: dict[str, Any] | None
    ) -> list[Evidence]:
        fused, req_of = self._candidates(job, persona, filters)
        cands = [
            to_evidence(c, s, {"rrf": s}, requirement=req_of.get(c.chunk_id))
            for c, s in fused[: self.candidate_k]
        ]
        if self.rerank and cands:
            scores = embeddings.rerank_scores(
                job_query_text(job)[:2000], [f"{e.title}. {e.excerpt}" for e in cands]
            )
            for e, sc in zip(cands, scores, strict=True):
                e.scores["rerank"] = round(float(sc), 4)
                e.score = round(float(sc), 4)
            cands.sort(key=lambda e: -e.score)
        return cands[:k]

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        if self._outcome is not None:
            # OutcomeAware calls back into self._core through `base.retrieve`; avoid recursion by
            # temporarily routing through a thin proxy
            proxy = _Proxy(self)
            self._outcome.base = proxy
            ev = self._outcome.retrieve(job, persona, k=k, filters=filters)
        else:
            ev = self._core(job, persona, k, filters)
        if self.corrective:
            from rag.variants.v8_corrective import CorrectiveRAG

            crag = CorrectiveRAG(self.res, base=_Proxy(self, outcome=self._outcome))
            ev = crag.retrieve(job, persona, k=k, filters=filters)
        return ev


class _Proxy:
    def __init__(self, pipe: BestPipeline, outcome: OutcomeAware | None = None) -> None:
        self.pipe, self.outcome = pipe, outcome

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        if self.outcome is not None:
            self.outcome.base = _Proxy(self.pipe)
            return self.outcome.retrieve(job, persona, k=k, filters=filters)
        return self.pipe._core(job, persona, k, filters)
