from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.handoffs import (
    BidDecision,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    PriceQuote,
    ProposalDraft,
    RiskReport,
)
from agent.marketplace_port import MarketplaceError, make_marketplace
from agent.nodes.scout import fingerprint
from apps.api.auth.security import CurrentUser
from apps.api.db import JobRecord, Run, get_session
from apps.api.runtime import runtime
from apps.api.schemas import AnalyseOut, JobDetailOut, JobListItem, JobListOut, ScoutIn, ScoutOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _action(rec: JobRecord) -> str:
    if rec.status in ("submitted",):
        return "submitted"
    if rec.status == "drafted":
        return "review proposal"
    if rec.decision == "bid":
        return "bid"
    if rec.decision == "watch":
        return "watch"
    if rec.decision == "skip":
        return "skip"
    return "analyse"


def _item(rec: JobRecord) -> JobListItem:
    j = rec.job_json or {}
    return JobListItem(
        job_id=rec.job_id,
        title=rec.title,
        status=rec.status,
        decision=rec.decision,
        fit_score=rec.fit_score,
        risk_score=rec.risk_score,
        risk_flags=rec.risk_flags or [],
        price_amount=rec.price_amount,
        price_type=rec.price_type,
        connects_cost=rec.connects_cost,
        payment_type=j.get("payment_type"),
        budget=j.get("budget"),
        hourly_min=j.get("hourly_min"),
        hourly_max=j.get("hourly_max"),
        posted_at=j.get("posted_at"),
        first_seen_at=rec.first_seen_at,
        latest_thread_id=rec.latest_thread_id,
        recommended_action=_action(rec),
    )


@router.get("", response_model=JobListOut)
async def inbox(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    decision: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> JobListOut:
    stmt = select(JobRecord).where(JobRecord.user_id == user.user_id)
    if status:
        stmt = stmt.where(JobRecord.status == status)
    elif not decision:
        stmt = stmt.where(JobRecord.status != "dismissed")
    if decision:
        stmt = stmt.where(JobRecord.decision == decision)
    if q:
        stmt = stmt.where(func.lower(JobRecord.title).like(f"%{q.lower()}%"))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await session.scalars(
            stmt.order_by(JobRecord.fit_score.desc().nulls_last(), JobRecord.first_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return JobListOut(items=[_item(r) for r in rows], total=total)


@router.post("/scout", response_model=ScoutOut)
async def scout(
    body: ScoutIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ScoutOut:
    """Pull new jobs from the marketplace into this user's inbox (what the worker does on schedule)."""
    mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
    try:
        jobs = await mkt.search_jobs(body.query, skills=body.skills, limit=body.limit)
    except MarketplaceError as exc:
        raise HTTPException(503, f"marketplace unavailable: {exc}") from exc
    existing = {
        r.job_id: r
        for r in (
            await session.scalars(select(JobRecord).where(JobRecord.user_id == user.user_id))
        ).all()
    }
    fps = {r.fingerprint for r in existing.values() if r.fingerprint}
    new_ids: list[str] = []
    for j in jobs:
        d = j.model_dump()
        if j.job_id in existing:
            continue
        fp = fingerprint(d)
        rec = JobRecord(
            user_id=user.user_id,
            job_id=j.job_id,
            title=j.title,
            job_json=d,
            fingerprint=fp,
            connects_cost=j.connects_cost,
            status="dismissed" if fp in fps else "new",
            decision="skip" if fp in fps else None,
            risk_flags=["duplicate"] if fp in fps else [],
        )
        session.add(rec)
        if fp not in fps:
            new_ids.append(j.job_id)
        fps.add(fp)
    await session.commit()
    queued: list[str] = []
    if body.analyse:
        for jid in new_ids:
            queued.append(await runtime().start_bid(user, jid))
    return ScoutOut(found=len(jobs), new=len(new_ids), queued=queued)


async def _record(session: AsyncSession, user_id: str, job_id: str) -> JobRecord:
    rec = await session.scalar(
        select(JobRecord).where(JobRecord.user_id == user_id, JobRecord.job_id == job_id)
    )
    if rec is None:
        raise HTTPException(404, "job not in your inbox")
    return rec


@router.get("/{job_id}", response_model=JobDetailOut)
async def detail(
    job_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> JobDetailOut:
    rec = await _record(session, user.user_id, job_id)
    out: dict[str, Any] = {
        "job": rec.job_json,
        "record": _item(rec),
        "thread_id": rec.latest_thread_id,
    }
    if rec.latest_thread_id:
        values, _ = await runtime().state_values(rec.latest_thread_id, "bid", user.user_id)
        out["status"] = values.get("status")
        out["needs_attention_reason"] = values.get("needs_attention_reason")
        out["evidence"] = values.get("evidence", [])
        for key, model in (
            ("job_spec", JobSpec),
            ("risk_report", RiskReport),
            ("fit_report", FitReport),
            ("decision", BidDecision),
            ("price_quote", PriceQuote),
            ("proposal_draft", ProposalDraft),
            ("critique", Critique),
            ("compliance_verdict", ComplianceVerdict),
        ):
            if values.get(key):
                try:
                    out[key] = model.model_validate(values[key])
                except Exception:  # noqa: BLE001
                    out[key] = None
    return JobDetailOut(**out)


@router.post("/{job_id}/analyse", response_model=AnalyseOut, status_code=202)
async def analyse(
    job_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalyseOut:
    rec = await _record(session, user.user_id, job_id)
    if rec.latest_thread_id:
        run = await session.get(Run, rec.latest_thread_id)
        if run and run.status in ("queued", "running"):
            return AnalyseOut(thread_id=rec.latest_thread_id, status=run.status)
    thread_id = await runtime().start_bid(user, job_id, job=rec.job_json or None)
    return AnalyseOut(thread_id=thread_id, status="queued")


@router.post("/{job_id}/skip", response_model=JobListItem)
async def skip(
    job_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> JobListItem:
    rec = await _record(session, user.user_id, job_id)
    rec.status, rec.decision = "dismissed", "skip"
    await session.commit()
    return _item(rec)
