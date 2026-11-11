"""Portfolio: summary of what GigBid can cite, uploads for an own profile, incremental re-index.

Demo personas are read-only (their corpora are committed). A user on an own profile gets a
private corpus at data/personas/user_<id>/; every upload is converted into the loader's layout
and indexed incrementally in the background (only changed chunks are re-embedded)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from apps.api.auth.security import CurrentUser
from apps.api.db import PortfolioItem, User, get_session, session_factory, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"])
PERSONAS_ROOT = settings.ROOT / "data/personas"
MAX_BYTES = 5 * 1024 * 1024
UploadKind = Literal["cv", "case_study", "proposals", "reviews"]


def persona_key(user: User) -> str:
    return f"user_{user.user_id}" if user.persona == "own" else user.persona


class ProjectOut(BaseModel):
    id: str
    name: str
    year: int | None = None
    client_industry: str | None = None
    skills: list[str] = Field(default_factory=list)
    has_repo: bool = False


class PortfolioItemOut(BaseModel):
    item_id: str
    kind: str
    title: str
    verified: bool
    ingested_at: str | None
    created_at: str


class PortfolioOut(BaseModel):
    persona: str
    persona_key: str
    editable: bool
    counts: dict[str, int]
    projects: list[ProjectOut]
    top_skills: list[str]
    items: list[PortfolioItemOut]
    indexed_chunks: int


def _projects(key: str) -> list[dict[str, Any]]:
    p = PERSONAS_ROOT / key / "projects.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "item"


@router.get("", response_model=PortfolioOut)
async def summary(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> PortfolioOut:
    key = persona_key(user)
    d = PERSONAS_ROOT / key
    counts = {
        "case_studies": len(list((d / "case_studies").glob("*.md"))) if d.exists() else 0,
        "repos": len([p for p in (d / "repos").glob("*") if p.is_dir()])
        if (d / "repos").exists()
        else 0,
        "proposals": sum(1 for _ in (d / "proposals.jsonl").open(encoding="utf-8"))
        if (d / "proposals.jsonl").exists()
        else 0,
        "reviews": sum(1 for _ in (d / "reviews.jsonl").open(encoding="utf-8"))
        if (d / "reviews.jsonl").exists()
        else 0,
        "cv": int((d / "cv.pdf").exists() or (d / "cv.md").exists()),
    }
    projects = [
        ProjectOut(
            id=p["id"],
            name=p.get("name", p["id"]),
            year=p.get("year"),
            client_industry=p.get("client_industry"),
            skills=p.get("skills", [])[:6],
            has_repo=bool(p.get("has_repo")),
        )
        for p in _projects(key)
    ]
    skill_count: dict[str, int] = {}
    for p in _projects(key):
        for s in p.get("skills", []) + p.get("libraries", []):
            skill_count[s] = skill_count.get(s, 0) + 1
    rows = (
        await session.scalars(
            select(PortfolioItem)
            .where(PortfolioItem.user_id == user.user_id)
            .order_by(PortfolioItem.created_at.desc())
        )
    ).all()
    chunks = 0
    try:
        from rag.index.pg import ChunkStore

        chunks = await asyncio.to_thread(lambda: ChunkStore().count(key))
    except Exception as exc:  # noqa: BLE001 - summary still useful without the index
        log.warning("chunk count unavailable: %s", exc)
    return PortfolioOut(
        persona=user.persona,
        persona_key=key,
        editable=user.persona == "own",
        counts=counts,
        projects=projects,
        top_skills=[k for k, _ in sorted(skill_count.items(), key=lambda kv: -kv[1])[:24]],
        items=[
            PortfolioItemOut(
                item_id=r.item_id,
                kind=r.kind,
                title=r.title,
                verified=r.verified,
                ingested_at=r.ingested_at.isoformat() if r.ingested_at else None,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ],
        indexed_chunks=chunks,
    )


def _extract_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", errors="ignore")


async def _reindex(user_id: str, key: str) -> None:
    from rag.index.pg import ChunkStore
    from rag.ingest.cli import ingest_persona

    try:
        stats = await asyncio.to_thread(lambda: ingest_persona(ChunkStore(), PERSONAS_ROOT / key))
        log.info("re-indexed %s: %s", key, stats)
        async with session_factory()() as s:
            for row in (
                await s.scalars(
                    select(PortfolioItem).where(
                        PortfolioItem.user_id == user_id, PortfolioItem.ingested_at.is_(None)
                    )
                )
            ).all():
                row.ingested_at = utcnow()
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("re-index of %s failed: %s", key, exc)


@router.post("/upload", response_model=PortfolioItemOut, status_code=201)
async def upload(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    background: BackgroundTasks,
    kind: Annotated[UploadKind, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()] = "",
    skills: Annotated[str, Form(description="comma-separated skills this item shows")] = "",
    year: Annotated[int | None, Form()] = None,
    client_industry: Annotated[str, Form()] = "",
) -> PortfolioItemOut:
    if user.persona != "own":
        raise HTTPException(
            400,
            "demo personas are read-only; switch to an own profile in Settings to upload your portfolio",
        )
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file larger than 5 MB")
    name = file.filename or "upload"
    if not re.search(r"\.(pdf|md|txt|jsonl|json)$", name, re.I):
        raise HTTPException(415, "accepted formats: PDF, Markdown, text, JSONL")
    key = persona_key(user)
    d = PERSONAS_ROOT / key
    (d / "case_studies").mkdir(parents=True, exist_ok=True)
    title = title or name.rsplit(".", 1)[0]
    if kind == "cv":
        if name.lower().endswith(".pdf"):
            (d / "cv.pdf").write_bytes(data)
        else:
            (d / "cv.md").write_text(_extract_text(name, data), encoding="utf-8")
    elif kind == "case_study":
        projects = _projects(key)
        pid = f"p{len(projects) + 1:02d}"
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]
        projects.append(
            {
                "id": pid,
                "name": title,
                "year": year,
                "client_industry": client_industry or None,
                "skills": skill_list,
                "libraries": [],
                "has_repo": False,
                "source": "upload",
            }
        )
        (d / "projects.json").write_text(
            json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        front = f"---\nproject_id: {pid}\nyear: {year or ''}\nclient_industry: {client_industry}\nskills: {json.dumps(skill_list)}\nlibraries: []\n---\n\n"
        body = _extract_text(name, data).strip()
        if not body.startswith("#"):
            body = f"# {title}\n\n{body}"
        (d / "case_studies" / f"{pid}_{_slug(title)}.md").write_text(
            front + body + "\n", encoding="utf-8"
        )
    elif kind in ("proposals", "reviews"):
        target = d / ("proposals.jsonl" if kind == "proposals" else "reviews.jsonl")
        lines = [ln for ln in _extract_text(name, data).splitlines() if ln.strip()]
        valid = []
        for i, ln in enumerate(lines):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, f"line {i + 1} is not valid JSON") from exc
            if kind == "proposals":
                if "cover_letter" not in obj or obj.get("outcome") not in (
                    "won",
                    "replied",
                    "ignored",
                ):
                    raise HTTPException(
                        422,
                        f"line {i + 1}: proposals need cover_letter and outcome won|replied|ignored",
                    )
                obj.setdefault("proposal_id", f"{key}_prop_up_{i + 1:03d}")
            elif "text" not in obj:
                raise HTTPException(422, f"line {i + 1}: reviews need a text field")
            valid.append(json.dumps(obj, ensure_ascii=False))
        with target.open("a", encoding="utf-8") as f:
            f.write("\n".join(valid) + "\n")
    row = PortfolioItem(
        user_id=user.user_id,
        kind=kind,
        title=title,
        path=str((d).relative_to(settings.ROOT)),
        meta={"filename": name, "bytes": len(data)},
    )
    session.add(row)
    await session.commit()
    background.add_task(_reindex, user.user_id, key)
    return PortfolioItemOut(
        item_id=row.item_id,
        kind=row.kind,
        title=row.title,
        verified=row.verified,
        ingested_at=None,
        created_at=row.created_at.isoformat(),
    )


@router.post("/reindex", status_code=202)
async def reindex(user: CurrentUser, background: BackgroundTasks) -> dict[str, str]:
    background.add_task(_reindex, user.user_id, persona_key(user))
    return {"status": "queued", "persona_key": persona_key(user)}
