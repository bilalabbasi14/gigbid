"""Loaders and chunkers on the committed persona corpus (no DB, no models)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.settings import ROOT
from rag.ingest.chunkers import chunk_document
from rag.ingest.loaders import load_persona
from rag.schema import Document

PERSONA = ROOT / "data/personas/ai_ml"


@pytest.mark.skipif(not (PERSONA / "projects.json").exists(), reason="persona corpus not generated")
def test_loader_covers_every_doc_type():
    docs = list(load_persona(PERSONA))
    types = {d.doc_type for d in docs}
    assert {"cv", "case_study", "readme", "code", "review", "proposal", "manifest"} <= types
    cs = [d for d in docs if d.doc_type == "case_study"]
    assert all(d.project_id for d in cs)
    props = [d for d in docs if d.doc_type == "proposal"]
    assert all(d.outcome in {"won", "replied", "ignored"} for d in props)
    assert all(d.job_id for d in props)
    code = [d for d in docs if d.doc_type == "code"]
    assert all(d.language for d in code) and all(d.project_id for d in code)


def test_chunker_prose_and_code_and_whole_items(tmp_path: Path):
    prose = Document(
        doc_id="d1",
        persona="p",
        doc_type="case_study",
        title="T",
        text="# Title\n\n" + ("word " * 700) + "\n\n## Results\n\n" + ("metric " * 100),
        source_path="x.md",
        project_id="p01",
    )
    chunks = chunk_document(prose, size=200, overlap=20)
    assert len(chunks) >= 5 and all(c.content_hash for c in chunks)
    assert chunks[-1].title.endswith("Results")
    code = Document(
        doc_id="d2",
        persona="p",
        doc_type="code",
        title="a.py",
        text="import os\n\ndef a():\n    return 1\n\nclass B:\n    pass\n",
        source_path="a.py",
        language="python",
    )
    cc = chunk_document(code, size=512)
    assert len(cc) == 1 and "class B" in cc[0].text
    review = Document(
        doc_id="d3",
        persona="p",
        doc_type="review",
        title="r",
        text="Great work.",
        source_path="r.jsonl",
    )
    assert len(chunk_document(review)) == 1


def test_chunk_ids_are_stable():
    doc = Document(
        doc_id="d9",
        persona="p",
        doc_type="readme",
        title="R",
        text="hello world " * 50,
        source_path="README.md",
    )
    a = chunk_document(doc)
    b = chunk_document(doc)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
