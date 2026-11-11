"""Shared RAG types: documents, chunks and evidence items returned to agents."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["cv", "case_study", "readme", "code", "review", "proposal", "manifest"]
Outcome = Literal["won", "replied", "ignored"] | None


class Document(BaseModel):
    doc_id: str
    persona: str
    doc_type: DocType
    title: str
    text: str
    source_path: str
    project_id: str | None = None
    repo_slug: str | None = None
    skills: list[str] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)
    year: int | None = None
    client_industry: str | None = None
    outcome: Outcome = None
    job_id: str | None = None  # proposals only
    language: str | None = None  # code only
    extra: dict = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    persona: str
    doc_type: DocType
    title: str
    text: str
    position: int
    project_id: str | None = None
    repo_slug: str | None = None
    skills: list[str] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)
    year: int | None = None
    client_industry: str | None = None
    outcome: Outcome = None
    job_id: str | None = None
    source_path: str
    context: str = ""  # V6 contextual retrieval: generated context line
    content_hash: str = ""

    def with_hash(self) -> Chunk:
        self.content_hash = hashlib.sha256(
            f"{self.doc_id}|{self.position}|{self.text}|{self.context}".encode()
        ).hexdigest()[:32]
        return self

    def embed_text(self) -> str:
        head = f"{self.title} ({self.doc_type}"
        if self.project_id:
            head += f", project {self.project_id}"
        if self.year:
            head += f", {self.year}"
        head += ")"
        ctx = f"{self.context}\n" if self.context else ""
        return f"{head}\n{ctx}{self.text}"


class Evidence(BaseModel):
    """What the Portfolio MCP server returns and what the Writer may cite."""

    evidence_id: str  # chunk_id
    doc_id: str
    project_id: str | None
    doc_type: DocType
    title: str
    excerpt: str
    source_path: str
    skills: list[str] = Field(default_factory=list)
    year: int | None = None
    client_industry: str | None = None
    outcome: Outcome = None
    job_id: str | None = None  # proposals: the job it was sent for
    score: float = 0.0
    scores: dict[str, float] = Field(
        default_factory=dict
    )  # per-signal breakdown (dense, bm25, rerank, outcome)
    matched_requirement: str | None = None


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode(), usedforsecurity=False).hexdigest()[:16]
