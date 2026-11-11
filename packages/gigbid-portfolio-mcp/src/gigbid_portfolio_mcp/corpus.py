"""Load a portfolio folder into searchable items.

Accepts the GigBid layout (projects.json, case_studies/*.md with front matter, repos/<name>/...,
cv.pdf or cv.md, proposals.jsonl, reviews.jsonl) or any folder of .md, .txt and .pdf files, where
each file is one item. Search is BM25 over paragraph-sized chunks, then grouped per item."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rank_bm25 import BM25Plus

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".go", ".rs", ".java", ".rb"}
TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-_]{1,}")


def tokenize(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        out.append(t)
        s = re.sub(r"[.\-_#+]+$", "", t)
        if s != t:
            out.append(s)
    return out


@dataclass
class Item:
    item_id: str
    type: str  # case_study | cv | readme | code | review | proposal | document
    title: str
    text: str
    source: str
    project_id: str | None = None
    date: str | None = None
    outcome: str | None = None
    skills: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    item: Item
    text: str


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, text[m.end() :]
    except yaml.YAMLError:
        return {}, text[m.end() :]


def _title(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


class Portfolio:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"portfolio folder not found: {self.root}")
        self.items: list[Item] = []
        self.projects: dict[str, dict[str, Any]] = {}
        self._load()
        self.chunks = [Chunk(it, para) for it in self.items for para in self._paragraphs(it)]
        self._tokens = [
            tokenize(f"{c.item.title} {' '.join(c.item.skills)} {c.text}") for c in self.chunks
        ]
        self._token_sets = [set(t) for t in self._tokens]
        # BM25Plus keeps IDF positive on small corpora (BM25Okapi scores a term found in half of a
        # two-file portfolio as zero, so tiny portfolios returned nothing)
        self._bm25 = BM25Plus(self._tokens) if self.chunks else None

    # ---------------------------------------------------------------- loading
    def _load(self) -> None:
        r = self.root
        pj = r / "projects.json"
        if pj.exists():
            self.projects = {p["id"]: p for p in json.loads(pj.read_text(encoding="utf-8"))}
        structured = pj.exists() or (r / "case_studies").exists()
        if not structured:
            for f in sorted(r.rglob("*")):
                if f.is_file() and f.suffix.lower() in (".md", ".txt", ".pdf"):
                    text = (
                        _pdf(f)
                        if f.suffix.lower() == ".pdf"
                        else f.read_text(encoding="utf-8", errors="ignore")
                    )
                    meta, body = _front_matter(text)
                    self.items.append(
                        Item(
                            item_id=f"doc{len(self.items) + 1:03d}",
                            type="document",
                            title=_title(body, f.stem),
                            text=body,
                            source=str(f.relative_to(r)),
                            skills=list(meta.get("skills") or []),
                            date=str(meta.get("year") or "") or None,
                        )
                    )
            return
        for name in ("cv.pdf", "cv.md"):
            f = r / name
            if f.exists():
                self.items.append(
                    Item(
                        item_id="cv",
                        type="cv",
                        title="CV",
                        text=_pdf(f) if name.endswith(".pdf") else f.read_text(encoding="utf-8"),
                        source=name,
                    )
                )
                break
        for f in sorted((r / "case_studies").glob("*.md")):
            meta, body = _front_matter(f.read_text(encoding="utf-8"))
            pid = meta.get("project_id")
            proj = self.projects.get(pid, {})
            self.items.append(
                Item(
                    item_id=f"case:{f.stem}",
                    type="case_study",
                    title=_title(body, f.stem),
                    text=body,
                    source=str(f.relative_to(r)),
                    project_id=pid,
                    date=str(meta.get("year") or proj.get("year") or "") or None,
                    skills=list(meta.get("skills") or proj.get("skills") or [])
                    + list(meta.get("libraries") or proj.get("libraries") or []),
                )
            )
        for repo in sorted(p for p in (r / "repos").glob("*") if p.is_dir()):
            pidf = repo / ".project_id"
            pid = pidf.read_text(encoding="utf-8").strip() if pidf.exists() else None
            proj = self.projects.get(pid or "", {})
            for f in sorted(repo.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if f.name.lower() == "readme.md":
                    self.items.append(
                        Item(
                            item_id=f"readme:{repo.name}",
                            type="readme",
                            title=_title(f.read_text(encoding="utf-8"), repo.name),
                            text=f.read_text(encoding="utf-8"),
                            source=str(f.relative_to(r)),
                            project_id=pid,
                            skills=list(proj.get("skills", [])),
                        )
                    )
                elif f.suffix in CODE_EXT:
                    self.items.append(
                        Item(
                            item_id=f"code:{repo.name}/{f.relative_to(repo).as_posix()}",
                            type="code",
                            title=f"{repo.name}/{f.relative_to(repo).as_posix()}",
                            text=f.read_text(encoding="utf-8", errors="ignore")[:20000],
                            source=str(f.relative_to(r)),
                            project_id=pid,
                            skills=list(proj.get("libraries", [])),
                        )
                    )
        for name, kind in (("reviews.jsonl", "review"), ("proposals.jsonl", "proposal")):
            f = r / name
            if not f.exists():
                continue
            for i, line in enumerate(
                x for x in f.read_text(encoding="utf-8").splitlines() if x.strip()
            ):
                d = json.loads(line)
                pid = d.get("project_id") or (d.get("project_ids") or [None])[0]
                text = d.get("text") or d.get("cover_letter") or ""
                title = (
                    f"Client review ({d.get('rating', '?')}/5)"
                    if kind == "review"
                    else f"Past proposal: {d.get('job_title', '')[:70]}"
                )
                self.items.append(
                    Item(
                        item_id=d.get("review_id") or d.get("proposal_id") or f"{kind}{i + 1:03d}",
                        type=kind,
                        title=title,
                        text=text,
                        source=name,
                        project_id=pid,
                        date=str(d.get("year") or d.get("sent_year") or "") or None,
                        outcome=d.get("outcome"),
                    )
                )

    @staticmethod
    def _paragraphs(it: Item, size: int = 220) -> list[str]:
        if it.type in ("review", "proposal"):
            return [it.text]
        out, buf = [], []
        for para in re.split(r"\n\s*\n", it.text):
            if not para.strip():
                continue
            if sum(len(p.split()) for p in buf) + len(para.split()) > size and buf:
                out.append("\n\n".join(buf))
                buf = []
            buf.append(para.strip())
        if buf:
            out.append("\n\n".join(buf))
        return out or [it.text[:2000]]

    # ---------------------------------------------------------------- queries
    def search(
        self,
        requirement: str,
        k: int = 5,
        types: list[str] | None = None,
        outcome: str | None = None,
    ) -> list[tuple[Item, str, float]]:
        if not self._bm25:
            return []
        query = tokenize(requirement)
        qset = set(query)
        scores = self._bm25.get_scores(query)
        best: dict[str, tuple[Item, str, float]] = {}
        for i in sorted(range(len(scores)), key=lambda i: -scores[i]):
            if not (qset & self._token_sets[i]):
                continue  # BM25Plus gives every chunk a floor score; require a shared term
            c = self.chunks[i]
            if types and c.item.type not in types:
                continue
            if outcome and c.item.outcome != outcome:
                continue
            if c.item.item_id not in best:
                best[c.item.item_id] = (c.item, c.text, float(scores[i]))
            if len(best) >= k:
                break
        return list(best.values())

    def project(self, project_id: str) -> dict[str, Any] | None:
        items = [it for it in self.items if it.project_id == project_id]
        if not items and project_id not in self.projects:
            return None
        meta = self.projects.get(project_id, {})
        return {
            "project_id": project_id,
            "name": meta.get("name")
            or next((it.title for it in items if it.type == "case_study"), project_id),
            "year": meta.get("year"),
            "client_industry": meta.get("client_industry"),
            "skills": meta.get("skills", []),
            "libraries": meta.get("libraries", []),
            "outcome_metrics": meta.get("outcome_metrics", []),
            "case_study_markdown": "\n\n".join(it.text for it in items if it.type == "case_study")
            or None,
            "readme_markdown": "\n\n".join(it.text for it in items if it.type == "readme") or None,
            "code_files": [it.source for it in items if it.type == "code"],
            "reviews": [{"text": it.text, "date": it.date} for it in items if it.type == "review"],
        }

    def skills(self) -> list[dict[str, Any]]:
        agg: dict[str, dict[str, Any]] = {}
        for it in self.items:
            for s in it.skills:
                d = agg.setdefault(
                    s, {"skill": s, "projects": set(), "evidence_count": 0, "won_proposals": 0}
                )
                d["evidence_count"] += 1
                if it.project_id:
                    d["projects"].add(it.project_id)
        for it in self.items:
            if it.type == "proposal" and it.outcome == "won":
                for s, d in agg.items():
                    if s.lower() in it.text.lower():
                        d["won_proposals"] += 1
        return sorted(
            ({**d, "projects": sorted(d["projects"])} for d in agg.values()),
            key=lambda d: (-d["evidence_count"], d["skill"]),
        )
