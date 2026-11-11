"""Ingest persona corpora into pgvector + BM25. Incremental: unchanged chunks are skipped,
removed ones are deleted.

  uv run python -m rag.ingest.cli --all
  uv run python -m rag.ingest.cli --persona ai_ml [--contextual]   # V6 context lines
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from agent import settings
from rag import embeddings
from rag.index.bm25 import BM25Index
from rag.index.pg import ChunkStore
from rag.ingest.chunkers import chunk_document
from rag.ingest.loaders import load_persona
from rag.schema import Chunk

log = logging.getLogger("ingest")
PERSONAS_ROOT = settings.ROOT / "data/personas"


def build_chunks(persona_dir: Path, contextual: bool = False) -> list[Chunk]:
    cfg = settings.config().rag
    chunks: list[Chunk] = []
    docs = list(load_persona(persona_dir))
    for doc in docs:
        cs = chunk_document(
            doc, size=int(cfg.get("chunk_size", 512)), overlap=int(cfg.get("chunk_overlap", 64))
        )
        if contextual:
            from rag.variants.v6_contextual import add_context_lines

            cs = add_context_lines(doc, cs)
        chunks.extend(cs)
    log.info("%s: %d documents -> %d chunks", persona_dir.name, len(docs), len(chunks))
    return chunks


def ingest_persona(
    store: ChunkStore, persona_dir: Path, *, contextual: bool = False, force: bool = False
) -> dict[str, int]:
    # the contextual (V6) chunks live in their own index key so the normal index is untouched
    persona = persona_dir.name + ("__ctx" if contextual else "")
    t0 = time.time()
    chunks = build_chunks(persona_dir, contextual=contextual)
    existing = store.existing_hashes(persona)
    todo = [c for c in chunks if force or existing.get(c.chunk_id) != c.content_hash]
    stale = [cid for cid in existing if cid not in {c.chunk_id for c in chunks}]
    model_name = settings.config().models.embeddings["model"]
    for i in range(0, len(todo), 64):
        batch = todo[i : i + 64]
        vecs = embeddings.embed_documents([c.embed_text() for c in batch])
        store.upsert(batch, vecs, model_name)
        log.info("%s: embedded %d/%d", persona, min(i + 64, len(todo)), len(todo))
    store.delete_ids(stale)
    BM25Index(persona, store.all_chunks(persona)).save()
    stats = {
        "chunks": len(chunks),
        "embedded": len(todo),
        "deleted": len(stale),
        "seconds": round(time.time() - t0, 1),
    }
    log.info("%s: %s", persona, stats)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--contextual", action="store_true", help="V6: prepend generated context lines")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    personas = args.persona or (
        [
            d.name
            for d in PERSONAS_ROOT.iterdir()
            if d.is_dir() and not d.name.startswith(("_", "x3_"))  # x3_* are evaluation copies
        ]
        if args.all
        else []
    )
    if not personas:
        ap.error("pass --persona NAME or --all")
    store = ChunkStore()
    for p in personas:
        ingest_persona(store, PERSONAS_ROOT / p, contextual=args.contextual, force=args.force)


if __name__ == "__main__":
    main()
