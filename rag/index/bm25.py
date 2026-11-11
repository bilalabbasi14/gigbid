"""BM25 index over chunks, persisted to disk, rebuilt from the chunk store after ingestion."""

from __future__ import annotations

import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from agent.settings import ROOT
from rag.schema import Chunk

BM25_DIR = ROOT / "data/processed/bm25"
TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-_]{1,}")


def tokenize(text: str) -> list[str]:
    toks = TOKEN.findall(text.lower())
    # keep exact library names like "scikit-learn", "next.js", "c#" and also their stripped forms
    out = []
    for t in toks:
        out.append(t)
        stripped = re.sub(r"[.\-_#+]+$", "", t)
        if stripped != t:
            out.append(stripped)
    return out


class BM25Index:
    def __init__(self, persona: str, chunks: list[Chunk]) -> None:
        self.persona = persona
        self.chunk_ids = [c.chunk_id for c in chunks]
        self.meta = {c.chunk_id: c for c in chunks}
        self._bm25 = BM25Okapi([tokenize(c.embed_text()) for c in chunks]) if chunks else None

    def search(
        self, query: str, k: int = 10, doc_types: list[str] | None = None
    ) -> list[tuple[Chunk, float]]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out: list[tuple[Chunk, float]] = []
        for i in order:
            c = self.meta[self.chunk_ids[i]]
            if doc_types and c.doc_type not in doc_types:
                continue
            if scores[i] <= 0:
                break
            out.append((c, float(scores[i])))
            if len(out) >= k:
                break
        return out

    # ---- persistence ----
    @staticmethod
    def path(persona: str) -> Path:
        return BM25_DIR / f"{persona}.pkl"

    def save(self) -> None:
        BM25_DIR.mkdir(parents=True, exist_ok=True)
        with self.path(self.persona).open("wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, persona: str) -> BM25Index | None:
        p = cls.path(persona)
        if not p.exists():
            return None
        with p.open("rb") as f:
            return pickle.load(f)  # noqa: S301 - our own file
