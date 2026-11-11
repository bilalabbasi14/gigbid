"""Type-aware chunking. Prose splits on headings/paragraphs, code on top-level definitions,
short items (reviews, proposals) stay whole."""

from __future__ import annotations

import re

from rag.schema import Chunk, Document, stable_id


def _mk(doc: Document, pos: int, text: str, title: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=stable_id(doc.doc_id, str(pos)),
        doc_id=doc.doc_id,
        persona=doc.persona,
        doc_type=doc.doc_type,
        title=title or doc.title,
        text=text.strip(),
        position=pos,
        project_id=doc.project_id,
        repo_slug=doc.repo_slug,
        skills=doc.skills,
        libraries=doc.libraries,
        year=doc.year,
        client_industry=doc.client_industry,
        outcome=doc.outcome,
        job_id=doc.job_id,
        source_path=doc.source_path,
    ).with_hash()


def _window(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    out, i = [], 0
    while i < len(words):
        out.append(" ".join(words[i : i + size]))
        if i + size >= len(words):
            break
        i += size - overlap
    return out


def chunk_prose(doc: Document, size: int, overlap: int) -> list[Chunk]:
    # split on markdown headings, then pack paragraphs up to `size` words
    sections = re.split(r"\n(?=#{1,3}\s)", doc.text)
    pieces: list[tuple[str, str]] = []
    for sec in sections:
        m = re.match(r"#{1,3}\s+(.+)", sec)
        heading = m.group(1).strip() if m else doc.title
        buf: list[str] = []
        for para in re.split(r"\n\s*\n", sec):
            if not para.strip():
                continue
            if sum(len(p.split()) for p in buf) + len(para.split()) > size and buf:
                pieces.append((heading, "\n\n".join(buf)))
                buf = []
            buf.append(para.strip())
        if buf:
            pieces.append((heading, "\n\n".join(buf)))
    chunks: list[Chunk] = []
    for heading, text in pieces:
        for w in _window(text, size, overlap):
            chunks.append(
                _mk(
                    doc,
                    len(chunks),
                    w,
                    title=f"{doc.title} - {heading}" if heading != doc.title else doc.title,
                )
            )
    return chunks or [_mk(doc, 0, doc.text)]


def chunk_code(doc: Document, size: int) -> list[Chunk]:
    lines = doc.text.splitlines()
    boundaries = [
        i
        for i, ln in enumerate(lines)
        if re.match(
            r"^(def |class |async def |export |function |const \w+ = |interface |type )", ln
        )
    ]
    if not boundaries or boundaries[0] != 0:
        boundaries = [0, *boundaries]
    blocks = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    # pack small blocks together
    chunks, buf = [], []
    for b in blocks:
        if sum(len(x.split()) for x in buf) + len(b.split()) > size and buf:
            chunks.append(_mk(doc, len(chunks), "\n".join(buf)))
            buf = []
        buf.append(b)
    if buf:
        chunks.append(_mk(doc, len(chunks), "\n".join(buf)))
    return chunks


def chunk_document(doc: Document, size: int = 512, overlap: int = 64) -> list[Chunk]:
    if doc.doc_type in ("review", "proposal", "manifest"):
        return [_mk(doc, 0, doc.text)]
    if doc.doc_type == "code":
        return chunk_code(doc, size)
    return chunk_prose(doc, size, overlap)
