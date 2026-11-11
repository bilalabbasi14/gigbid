from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.pii import mask_pii_in
from apps.api.auth.security import CurrentUser
from apps.api.db import Run, get_session
from apps.api.runtime import runtime
from apps.api.schemas import AnalyseOut, ReplayIn, RunDetailOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


def _out(r: Run) -> RunOut:
    return RunOut(
        thread_id=r.thread_id,
        kind=r.kind,
        job_id=r.job_id,
        status=r.status,
        current_node=r.current_node,
        created_at=r.created_at,
        updated_at=r.updated_at,
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        usage=r.usage_json or {},
        trace_url=r.trace_url,
        needs_attention_reason=r.needs_attention_reason,
    )


@router.get("", response_model=list[RunOut])
async def list_runs(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, le=200),
) -> list[RunOut]:
    stmt = select(Run).where(Run.user_id == user.user_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if kind:
        stmt = stmt.where(Run.kind == kind)
    rows = (await session.scalars(stmt.order_by(Run.created_at.desc()).limit(limit))).all()
    return [_out(r) for r in rows]


@router.get("/{thread_id}", response_model=RunDetailOut)
async def run_detail(
    thread_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> RunDetailOut:
    r = await session.get(Run, thread_id)
    if r is None or r.user_id != user.user_id:
        raise HTTPException(404, "run not found")
    values, _ = await runtime().state_values(thread_id, r.kind, user.user_id)
    trace = mask_pii_in(values.get("trace", []))
    state = {k: v for k, v in values.items() if k not in ("trace",)}
    checkpoints = await runtime().history(thread_id, r.kind, user.user_id, limit=30)
    return RunDetailOut(
        **_out(r).model_dump(), trace=trace, state=mask_pii_in(state), checkpoints=checkpoints
    )


@router.post("/{thread_id}/replay", response_model=AnalyseOut, status_code=202)
async def replay(
    thread_id: str,
    body: ReplayIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalyseOut:
    """Time travel: fork a new thread from a checkpoint of this run and continue from there."""
    r = await session.get(Run, thread_id)
    if r is None or r.user_id != user.user_id:
        raise HTTPException(404, "run not found")
    new_thread = await runtime().replay(thread_id, r.kind, user, body.checkpoint_id)
    return AnalyseOut(thread_id=new_thread, status="queued")
