from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.marketplace_port import MarketplaceError, make_marketplace
from apps.api.auth.security import CurrentUser
from apps.api.db import PipelineCard, Run, get_session
from apps.api.runtime import runtime
from apps.api.schemas import AnalyseOut, MessageApprovalPayload, MessagesOut, ThreadOut

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/threads", response_model=list[ThreadOut])
async def threads(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ThreadOut]:
    mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
    try:
        items = await mkt.list_threads()
    except MarketplaceError as exc:
        raise HTTPException(503, f"marketplace unavailable: {exc}") from exc
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.user_id == user.user_id, Run.kind == "conversation")
            .order_by(Run.created_at.desc())
        )
    ).all()
    latest: dict[str, Run] = {}
    for r in runs:
        if r.marketplace_thread_id and r.marketplace_thread_id not in latest:
            latest[r.marketplace_thread_id] = r
    out = []
    for t in items:
        r = latest.get(t.thread_id)
        out.append(
            ThreadOut(
                marketplace_thread_id=t.thread_id,
                job_id=t.job_id,
                job_title=t.job_title,
                status=t.status,
                unread=t.unread,
                last_message=t.last_message,
                conversation_thread_id=r.thread_id if r else None,
                pending_approval=bool(r and r.status == "awaiting_approval"),
            )
        )
    return out


@router.get("/{marketplace_thread_id}", response_model=MessagesOut)
async def messages(
    marketplace_thread_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessagesOut:
    mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
    try:
        items = await mkt.list_messages(marketplace_thread_id)
    except MarketplaceError as exc:
        raise HTTPException(503, f"marketplace unavailable: {exc}") from exc
    r = await session.scalar(
        select(Run)
        .where(
            Run.user_id == user.user_id,
            Run.kind == "conversation",
            Run.marketplace_thread_id == marketplace_thread_id,
        )
        .order_by(Run.created_at.desc())
    )
    suggested = None
    if r and r.status == "awaiting_approval":
        raw = await runtime().pending_payload(r.thread_id, "conversation", user.user_id)
        suggested = MessageApprovalPayload.model_validate(raw) if raw else None
    return MessagesOut(
        marketplace_thread_id=marketplace_thread_id,
        items=[m.model_dump() for m in items],
        suggested_reply=suggested,
        conversation_thread_id=r.thread_id if r else None,
    )


@router.post("/{marketplace_thread_id}/draft", response_model=AnalyseOut, status_code=202)
async def draft(
    marketplace_thread_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalyseOut:
    """Run the conversation graph for this thread: classify the latest client message, draft a reply,
    and stop for approval."""
    card = await session.scalar(
        select(PipelineCard).where(
            PipelineCard.user_id == user.user_id,
            PipelineCard.marketplace_thread_id == marketplace_thread_id,
        )
    )
    thread_id = await runtime().start_conversation(
        user, marketplace_thread_id, job_id=card.job_id if card else None
    )
    return AnalyseOut(thread_id=thread_id, status="queued")
