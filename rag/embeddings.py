"""Open embedding and reranker models on CPU (sentence-transformers). Lazy singletons."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from agent import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    cfg = settings.config().models.embeddings
    name = cfg["model"]
    log.info("loading embedding model %s", name)
    return SentenceTransformer(name, device="cpu")


def embed_documents(texts: list[str], batch_size: int = 16) -> np.ndarray:
    cfg = settings.config().models.embeddings
    prefix = cfg.get("document_prefix", "")
    return _embedder().encode(
        [prefix + t for t in texts],
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )


def embed_query(text: str) -> np.ndarray:
    cfg = settings.config().models.embeddings
    return _embedder().encode(
        [cfg.get("query_prefix", "") + text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0]


def dimensions() -> int:
    return int(settings.config().models.embeddings.get("dimensions", 768))


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder

    name = settings.config().models.reranker["model"]
    log.info("loading reranker %s", name)
    return CrossEncoder(name, device="cpu")


def rerank_scores(query: str, passages: list[str], batch_size: int = 8) -> list[float]:
    if not passages:
        return []
    scores = _reranker().predict(
        [(query, p) for p in passages],
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [float(s) for s in np.asarray(scores).reshape(-1)]


def warm(reranker: bool = True) -> None:
    """Load the models once (startup), so the first node call does not pay for it."""
    _embedder()
    if reranker:
        _reranker()
