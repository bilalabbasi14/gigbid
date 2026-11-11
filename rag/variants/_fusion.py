"""Reciprocal rank fusion and small helpers shared by variants."""

from __future__ import annotations

from collections.abc import Sequence

from agent import settings
from rag.schema import Chunk


def rrf(
    ranked_lists: Sequence[Sequence[tuple[Chunk, float]]], k: int | None = None
) -> list[tuple[Chunk, float]]:
    k = k or int(settings.config().rag.get("hybrid_rrf_k", 60))
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for lst in ranked_lists:
        for rank, (chunk, _) in enumerate(lst, 1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(chunk.chunk_id, chunk)
    order = sorted(scores, key=lambda cid: -scores[cid])
    return [(chunks[cid], scores[cid]) for cid in order]


def dedupe(hits: Sequence[tuple[Chunk, float]]) -> list[tuple[Chunk, float]]:
    seen: set[str] = set()
    out = []
    for c, s in hits:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            out.append((c, s))
    return out
