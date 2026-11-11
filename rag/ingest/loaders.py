"""Loaders: persona folder -> Documents (CV PDF, markdown case studies, repo README + code, reviews, proposals)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import yaml

from rag.schema import Document, stable_id

CODE_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}
MANIFESTS = {
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "Pipfile",
    "environment.yml",
    "go.mod",
    "Cargo.toml",
}


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, text[m.end() :]


def _title(md: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else fallback


def load_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def load_persona(persona_dir: Path) -> Iterator[Document]:
    persona = persona_dir.name
    projects = {}
    pj = persona_dir / "projects.json"
    if pj.exists():
        projects = {p["id"]: p for p in json.loads(pj.read_text(encoding="utf-8"))}

    # CV: prefer the PDF (exercises the PDF path), fall back to markdown.
    cv_pdf, cv_md = persona_dir / "cv.pdf", persona_dir / "cv.md"
    if cv_pdf.exists() or cv_md.exists():
        text = load_pdf_text(cv_pdf) if cv_pdf.exists() else cv_md.read_text(encoding="utf-8")
        src = cv_pdf if cv_pdf.exists() else cv_md
        yield Document(
            doc_id=stable_id(persona, "cv"),
            persona=persona,
            doc_type="cv",
            title=f"CV ({persona})",
            text=text,
            source_path=str(src.relative_to(persona_dir.parent.parent)),
        )

    for f in sorted((persona_dir / "case_studies").glob("*.md")):
        meta, body = _front_matter(f.read_text(encoding="utf-8"))
        pid = meta.get("project_id")
        proj = projects.get(pid, {})
        yield Document(
            doc_id=stable_id(persona, "case", f.stem),
            persona=persona,
            doc_type="case_study",
            title=_title(body, f.stem),
            text=body.strip(),
            source_path=str(f.relative_to(persona_dir.parent.parent)),
            project_id=pid,
            repo_slug=proj.get("repo_slug"),
            skills=list(meta.get("skills") or proj.get("skills") or []),
            libraries=list(meta.get("libraries") or proj.get("libraries") or []),
            year=meta.get("year") or proj.get("year"),
            client_industry=meta.get("client_industry") or proj.get("client_industry"),
        )

    for repo in sorted(p for p in (persona_dir / "repos").glob("*") if p.is_dir()):
        pid_file = repo / ".project_id"
        pid = pid_file.read_text(encoding="utf-8").strip() if pid_file.exists() else None
        proj = projects.get(pid, {})
        for f in sorted(repo.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = str(f.relative_to(persona_dir.parent.parent))
            common = {
                "persona": persona,
                "source_path": rel,
                "project_id": pid,
                "repo_slug": repo.name,
                "year": proj.get("year"),
                "client_industry": proj.get("client_industry"),
                "skills": list(proj.get("skills") or []),
                "libraries": list(proj.get("libraries") or []),
            }
            if f.name.lower() == "readme.md":
                body = f.read_text(encoding="utf-8")
                yield Document(
                    doc_id=stable_id(persona, "readme", repo.name),
                    doc_type="readme",
                    title=_title(body, repo.name),
                    text=body,
                    **common,
                )
            elif f.name in MANIFESTS:
                yield Document(
                    doc_id=stable_id(persona, "manifest", repo.name, f.name),
                    doc_type="manifest",
                    title=f"{repo.name}/{f.name}",
                    text=f.read_text(encoding="utf-8", errors="ignore"),
                    **common,
                )
            elif f.suffix in CODE_EXT:
                yield Document(
                    doc_id=stable_id(persona, "code", repo.name, str(f.relative_to(repo))),
                    doc_type="code",
                    title=f"{repo.name}/{f.relative_to(repo).as_posix()}",
                    text=f.read_text(encoding="utf-8", errors="ignore"),
                    language=CODE_EXT[f.suffix],
                    **common,
                )

    rv = persona_dir / "reviews.jsonl"
    if rv.exists():
        for line in rv.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            proj = projects.get(r.get("project_id"), {})
            yield Document(
                doc_id=stable_id(persona, "review", r.get("review_id", r["text"][:40])),
                persona=persona,
                doc_type="review",
                title=f"Client review: {proj.get('name', r.get('project_id', ''))}",
                text=f"Rating {r.get('rating')}/5. {r['text']}",
                source_path=str(rv.relative_to(persona_dir.parent.parent)),
                project_id=r.get("project_id"),
                repo_slug=proj.get("repo_slug"),
                skills=list(proj.get("skills") or []),
                year=r.get("year") or proj.get("year"),
                client_industry=r.get("client_industry") or proj.get("client_industry"),
                extra={"rating": r.get("rating")},
            )

    pp = persona_dir / "proposals.jsonl"
    if pp.exists():
        for line in pp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            p = json.loads(line)
            pids = p.get("project_ids") or []
            skills: list[str] = []
            for pid in pids:
                skills += projects.get(pid, {}).get("skills", [])
            yield Document(
                doc_id=stable_id(persona, "proposal", p["proposal_id"]),
                persona=persona,
                doc_type="proposal",
                title=f"Past proposal: {p.get('job_title', '')[:80]}",
                text=p["cover_letter"],
                source_path=str(pp.relative_to(persona_dir.parent.parent)),
                project_id=pids[0] if pids else None,
                skills=sorted(set(skills))[:12],
                year=p.get("sent_year"),
                outcome=p.get("outcome"),
                job_id=p.get("job_id"),
                extra={
                    "project_ids": pids,
                    "bid_amount": p.get("bid_amount"),
                    "job_skills": p.get("job_skills", []),
                },
            )


def load_all(personas_root: Path, personas: list[str] | None = None) -> Iterator[Document]:
    for d in sorted(
        p for p in personas_root.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        if personas and d.name not in personas:
            continue
        yield from load_persona(d)
