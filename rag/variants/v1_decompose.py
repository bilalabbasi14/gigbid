"""V1 requirement decomposition: one dense retrieval per extracted requirement, merged by RRF.

Requirements come from a small-model call (prompt: fit_requirements); when the job dict already
carries `requirements` (the Fit Matcher passes them) no model call is made."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Chunk, Evidence
from rag.variants._fusion import rrf


class _Reqs(BaseModel):
    requirements: list[str] = Field(default_factory=list)


CACHE_PATH = settings.ROOT / "data/processed/requirements_cache.json"


def _cache() -> dict[str, list[str]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    return _CACHE


_CACHE: dict[str, list[str]] | None = None


def extract_requirements(job: dict[str, Any], max_n: int = 6) -> list[str]:
    if job.get("requirements"):
        return list(job["requirements"])[:max_n]
    key = job.get("job_id") or ""
    if key and key in _cache():
        return _cache()[key][:max_n]
    import asyncio

    from agent.guardrails import delimit_untrusted
    from agent.structured import call_structured

    async def _go() -> list[str]:
        reqs, _ = await call_structured(
            "fit_matcher",
            "fit_requirements",
            _Reqs,
            title=job.get("title", ""),
            skills=", ".join(job.get("skills") or []) or "none",
            job_text=delimit_untrusted(job.get("description", "")),
        )
        return [r for r in reqs.requirements if r.strip()][:max_n]

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():  # inside an async node: run in a worker thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            out = ex.submit(lambda: asyncio.run(_go())).result()
    else:
        out = asyncio.run(_go())
    out = out or [job.get("title", "")]
    if key:
        _cache()[key] = out
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache(), ensure_ascii=False, indent=0), encoding="utf-8")
    return out


class RequirementDecomposition:
    name = "v1_decompose"

    def __init__(self, resources: Resources, per_requirement_k: int = 6) -> None:
        self.res = resources
        self.per_k = per_requirement_k

    def per_requirement(
        self, job: dict[str, Any], persona: str, filters: dict[str, Any] | None
    ) -> list[tuple[str, list[tuple[Chunk, float]]]]:
        reqs = extract_requirements(job)
        out = []
        for r in reqs:
            q = embeddings.embed_query(r)
            out.append((r, self.res.store.dense_search(q, persona, k=self.per_k, filters=filters)))
        # the whole-post query stays in as one more ranked list so general context is not lost
        out.append(
            (
                "__whole_post__",
                self.res.store.dense_search(
                    embeddings.embed_query(job_query_text(job)),
                    persona,
                    k=self.per_k,
                    filters=filters,
                ),
            )
        )
        return out

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        lists = self.per_requirement(job, persona, filters)
        fused = rrf([[(c, s) for c, s in hits] for _, hits in lists])
        req_of: dict[str, str] = {}
        for r, hits in lists:
            for c, _ in hits:
                req_of.setdefault(c.chunk_id, r if r != "__whole_post__" else "")
        return [
            to_evidence(c, score, {"rrf": score}, requirement=req_of.get(c.chunk_id) or None)
            for c, score in fused[:k]
        ]
