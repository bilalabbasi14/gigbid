"""Retriever factory: the variant named in agent/config.yaml (or passed explicitly) is built here.

Every variant implements `retrieve(job, persona, k, filters) -> list[Evidence]` and is a plain
class under rag/variants/, so `make eval-rag` can run all of them against the same gold set.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

from agent import settings
from rag.index.bm25 import BM25Index
from rag.index.pg import ChunkStore
from rag.schema import Chunk, Evidence

VARIANTS = {
    "v0_naive": "rag.variants.v0_naive:NaiveDense",
    "v1_decompose": "rag.variants.v1_decompose:RequirementDecomposition",
    "v2_hybrid": "rag.variants.v2_hybrid:HybridRRF",
    "v3_rerank": "rag.variants.v3_rerank:CrossEncoderRerank",
    "v4_outcome": "rag.variants.v4_outcome:OutcomeAware",
    "v5_multivector": "rag.variants.v5_multivector:MultiVectorProjects",
    "v6_contextual": "rag.variants.v6_contextual:ContextualRetrieval",
    "v7_hyde": "rag.variants.v7_hyde:HyDE",
    "v8_corrective": "rag.variants.v8_corrective:CorrectiveRAG",
    "v9_skill_graph": "rag.variants.v9_skill_graph:SkillGraph",
    "best": "rag.variants.best:BestPipeline",
}


class Retriever(Protocol):
    name: str

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]: ...


class Resources:
    """Shared, lazily-built handles every variant uses."""

    def __init__(self, store: ChunkStore | None = None) -> None:
        self._store = store
        self._bm25: dict[str, BM25Index | None] = {}

    @property
    def store(self) -> ChunkStore:
        if self._store is None:
            self._store = ChunkStore()
        return self._store

    def bm25(self, persona: str) -> BM25Index:
        if persona not in self._bm25:
            idx = BM25Index.load(persona)
            if idx is None:
                idx = BM25Index(persona, self.store.all_chunks(persona))
            self._bm25[persona] = idx
        return self._bm25[persona]  # type: ignore[return-value]


def job_query_text(job: dict[str, Any]) -> str:
    skills = ", ".join(job.get("skills") or [])
    return f"{job.get('title', '')}\n{skills}\n{job.get('description', '')}"[:4000]


def to_evidence(
    chunk: Chunk,
    score: float,
    scores: dict[str, float] | None = None,
    requirement: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        project_id=chunk.project_id,
        doc_type=chunk.doc_type,
        title=chunk.title,
        excerpt=chunk.text[:1200],
        source_path=chunk.source_path,
        skills=chunk.skills,
        year=chunk.year,
        client_industry=chunk.client_industry,
        outcome=chunk.outcome,
        job_id=chunk.job_id,
        score=round(score, 4),
        scores={k: round(v, 4) for k, v in (scores or {}).items()},
        matched_requirement=requirement,
    )


def build_retriever(
    name: str | None = None, resources: Resources | None = None, **kw: Any
) -> Retriever:
    name = name or settings.config().rag.get("variant", "v0_naive")
    if name not in VARIANTS:
        raise ValueError(f"unknown RAG variant {name!r}; known: {sorted(VARIANTS)}")
    mod_name, _, cls_name = VARIANTS[name].partition(":")
    cls = getattr(importlib.import_module(mod_name), cls_name)
    return cls(resources or Resources(), **kw)
