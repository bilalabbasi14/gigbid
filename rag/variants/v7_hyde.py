"""V7 HyDE: embed a hypothetical ideal proposal paragraph for the job instead of the raw post.
Helps vague client posts whose wording looks nothing like the freelancer's case studies. The
generated text is a query only; it never reaches the writer or the client. Cached per job."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text, to_evidence
from rag.schema import Evidence
from rag.variants._fusion import rrf

CACHE_PATH = settings.ROOT / "data/processed/hyde_cache.json"
_CACHE: dict[str, str] | None = None


def _cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    return _CACHE


def hypothetical(job: dict[str, Any]) -> str:
    key = job.get("job_id") or ""
    if key and key in _cache():
        return _cache()[key]
    from agent.guardrails import delimit_untrusted
    from agent.structured import call_prompt

    async def _go() -> str:
        res = await call_prompt(
            "fit_matcher",
            "hyde",
            title=job.get("title", ""),
            skills=", ".join(job.get("skills") or []) or "none",
            job_text=delimit_untrusted(job.get("description", "")),
        )
        return res.text.strip()

    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            text = ex.submit(lambda: asyncio.run(_go())).result()
    except RuntimeError:
        text = asyncio.run(_go())
    if key and text:
        _cache()[key] = text
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache(), ensure_ascii=False), encoding="utf-8")
    return text


class HyDE:
    name = "v7_hyde"

    def __init__(self, resources: Resources, k_candidates: int = 15) -> None:
        self.res = resources
        self.k_candidates = k_candidates

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        try:
            hyp = hypothetical(job)
        except Exception:  # noqa: BLE001 - model unavailable: fall back to the post itself
            hyp = ""
        lists = [
            self.res.store.dense_search(
                embeddings.embed_query(job_query_text(job)),
                persona,
                k=self.k_candidates,
                filters=filters,
            )
        ]
        if hyp:
            lists.append(
                self.res.store.dense_search(
                    embeddings.embed_query(hyp), persona, k=self.k_candidates, filters=filters
                )
            )
        fused = rrf(lists)
        return [to_evidence(c, s, {"rrf": s, "hyde": 1.0 if hyp else 0.0}) for c, s in fused[:k]]
