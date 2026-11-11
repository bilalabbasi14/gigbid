"""V6 contextual retrieval: a generated context line prepended to each chunk before indexing, so
fragments that lose meaning out of context ("the pipeline cut latency by 40%") still match.

Deviation from the per-chunk recipe, recorded in the report: one context line per DOCUMENT (cached),
shared by its chunks with the chunk's own heading, to fit the free-tier quota (~240 calls instead of
600+). Contextual chunks live in a separate index (persona key `<persona>__ctx`) built with

    uv run python -m rag.ingest.cli --persona ai_ml --contextual

so the normal index is untouched. Retrieval is hybrid (BM25 + dense, RRF) over that index.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from agent import settings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Document, Evidence
from rag.variants.v2_hybrid import HybridRRF

CACHE_PATH = settings.ROOT / "data/processed/context_cache.json"
_CACHE: dict[str, str] | None = None
SUFFIX = "__ctx"


def _cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    return _CACHE


def _context_for(doc: Document) -> str:
    key = f"{doc.doc_id}:{hashlib.sha1(doc.text[:2000].encode(), usedforsecurity=False).hexdigest()[:10]}"
    if key in _cache():
        return _cache()[key]
    from agent.structured import call_prompt

    meta = {
        "project": doc.project_id,
        "year": doc.year,
        "industry": doc.client_industry,
        "skills": doc.skills[:8],
        "outcome": doc.outcome,
    }

    async def _go() -> str:
        res = await call_prompt(
            "scout",
            "contextual_chunk",
            doc_type=doc.doc_type,
            title=doc.title,
            meta=json.dumps(meta),
            text=doc.text[:3500],
        )
        return " ".join(res.text.split())[:400]

    try:
        text = asyncio.run(_go())
    except RuntimeError:  # already inside an event loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            text = ex.submit(lambda: asyncio.run(_go())).result()
    except Exception:  # noqa: BLE001 - model unavailable: fall back to metadata only
        text = (
            f"{doc.doc_type.replace('_', ' ')} '{doc.title}'"
            + (f", {doc.year}" if doc.year else "")
            + (f", {doc.client_industry}" if doc.client_industry else "")
        )
    _cache()[key] = text
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(_cache(), ensure_ascii=False), encoding="utf-8")
    return text


def add_context_lines(doc: Document, chunks: list[Chunk]) -> list[Chunk]:
    """Called by the ingestion CLI with --contextual: attach the document's context line to each
    chunk (and re-key the chunk into the contextual index)."""
    ctx = _context_for(doc)
    out = []
    for c in chunks:
        c.context = ctx
        c.persona = c.persona if c.persona.endswith(SUFFIX) else c.persona + SUFFIX
        c.chunk_id = c.chunk_id[:-4] + "ctx0" if len(c.chunk_id) >= 16 else c.chunk_id + "ctx0"
        out.append(c.with_hash())
    return out


class ContextualRetrieval:
    name = "v6_contextual"

    def __init__(self, resources: Resources) -> None:
        self.res = resources
        self.hybrid = HybridRRF(resources)

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        key = persona if persona.endswith(SUFFIX) else persona + SUFFIX
        fused, dense_s, sparse_s = self.hybrid.candidates(job_query_text(job), key, filters)  # type: ignore[misc]
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
