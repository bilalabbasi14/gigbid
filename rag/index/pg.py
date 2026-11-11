"""pgvector-backed chunk store: upsert by content hash, dense search, metadata filters."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from agent import settings
from rag.schema import Chunk

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class ChunkRow(Base):
    __tablename__ = "evidence_chunks"
    chunk_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(32), index=True)
    persona: Mapped[str] = mapped_column(String(32), index=True)
    doc_type: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    repo_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    libraries: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(32), index=True)
    embedding = mapped_column(Vector(768))
    embedding_model: Mapped[str] = mapped_column(String(128))
    indexed_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC).replace(tzinfo=None)
    )


Index("ix_chunks_persona_type", ChunkRow.persona, ChunkRow.doc_type)


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql://", "postgresql+psycopg://"
    )


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(_sync_url(url or settings.env().database_url), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON evidence_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )
    return engine


def row_to_chunk(r: ChunkRow) -> Chunk:
    return Chunk(
        chunk_id=r.chunk_id,
        doc_id=r.doc_id,
        persona=r.persona,
        doc_type=r.doc_type,
        title=r.title,
        text=r.text,
        position=r.position,
        project_id=r.project_id,
        repo_slug=r.repo_slug,
        skills=r.skills or [],
        libraries=r.libraries or [],
        year=r.year,
        client_industry=r.client_industry,
        outcome=r.outcome,
        job_id=r.job_id,
        source_path=r.source_path,
        context=r.context or "",
        content_hash=r.content_hash,
    )


class ChunkStore:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or make_engine()

    # ---- ingestion ----
    def existing_hashes(self, persona: str) -> dict[str, str]:
        with Session(self.engine) as s:
            return dict(
                s.execute(
                    select(ChunkRow.chunk_id, ChunkRow.content_hash).where(
                        ChunkRow.persona == persona
                    )
                ).all()
            )

    def upsert(self, chunks: list[Chunk], embeddings: np.ndarray, model_name: str) -> None:
        with Session(self.engine) as s:
            for c, e in zip(chunks, embeddings, strict=True):
                row = s.get(ChunkRow, c.chunk_id) or ChunkRow(chunk_id=c.chunk_id)
                for k, v in c.model_dump(exclude={"chunk_id"}).items():
                    setattr(row, k, v)
                row.embedding = e.tolist()
                row.embedding_model = model_name
                s.add(row)
            s.commit()

    def delete_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        with Session(self.engine) as s:
            s.execute(delete(ChunkRow).where(ChunkRow.chunk_id.in_(ids)))
            s.commit()

    def all_chunks(self, persona: str | None = None) -> list[Chunk]:
        with Session(self.engine) as s:
            stmt = select(ChunkRow)
            if persona:
                stmt = stmt.where(ChunkRow.persona == persona)
            return [row_to_chunk(r) for r in s.scalars(stmt).all()]

    def count(self, persona: str | None = None) -> int:
        with Session(self.engine) as s:
            stmt = select(ChunkRow.chunk_id)
            if persona:
                stmt = stmt.where(ChunkRow.persona == persona)
            return len(s.scalars(stmt).all())

    # ---- retrieval ----
    def dense_search(
        self,
        query_vec: np.ndarray,
        persona: str,
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        filters = filters or {}
        with Session(self.engine) as s:
            dist = ChunkRow.embedding.cosine_distance(query_vec.tolist())
            stmt = select(ChunkRow, dist.label("d")).where(ChunkRow.persona == persona)
            if filters.get("doc_types"):
                stmt = stmt.where(ChunkRow.doc_type.in_(filters["doc_types"]))
            if filters.get("project_id"):
                stmt = stmt.where(ChunkRow.project_id == filters["project_id"])
            if filters.get("outcome"):
                stmt = stmt.where(ChunkRow.outcome == filters["outcome"])
            if filters.get("min_year"):
                stmt = stmt.where(ChunkRow.year >= int(filters["min_year"]))
            rows = s.execute(stmt.order_by(dist).limit(k)).all()
            return [(row_to_chunk(r), float(1.0 - d)) for r, d in rows]

    def get(self, chunk_id: str) -> Chunk | None:
        with Session(self.engine) as s:
            r = s.get(ChunkRow, chunk_id)
            return row_to_chunk(r) if r else None

    def by_project(self, persona: str, project_id: str) -> list[Chunk]:
        with Session(self.engine) as s:
            rows = s.scalars(
                select(ChunkRow)
                .where(ChunkRow.persona == persona, ChunkRow.project_id == project_id)
                .order_by(ChunkRow.doc_type, ChunkRow.position)
            ).all()
            return [row_to_chunk(r) for r in rows]
