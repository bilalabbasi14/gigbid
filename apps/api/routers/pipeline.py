from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.marketplace_port import MarketplaceError, make_marketplace
from apps.api.auth.security import CurrentUser
from apps.api.db import PipelineCard, get_session, utcnow
from apps.api.runtime import runtime
from apps.api.schemas import PipelineCardOut, PipelineOut

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
EVENT_STAGE = {
    "proposal.viewed": "viewed",
    "proposal.replied": "replied",
    "proposal.interview": "interview",
    "proposal.hired": "hired",
    "proposal.lost": "lost",
    "message.received": "replied",
}


def _out(c: PipelineCard) -> PipelineCardOut:
    return PipelineCardOut(
        card_id=c.card_id,
        job_id=c.job_id,
        title=c.title,
        stage=c.stage,
        proposal_id=c.proposal_id,
        marketplace_thread_id=c.marketplace_thread_id,
        bid_thread_id=c.bid_thread_id,
        bid_amount=c.bid_amount,
        bid_type=c.bid_type,
        connects_spent=c.connects_spent,
        updated_at=c.updated_at,
        history=c.history or [],
    )


@router.get("", response_model=PipelineOut)
async def board(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> PipelineOut:
    rows = (
        await session.scalars(
            select(PipelineCard)
            .where(PipelineCard.user_id == user.user_id)
            .order_by(PipelineCard.updated_at.desc())
        )
    ).all()
    cols: dict[str, list[PipelineCardOut]] = {s: [] for s in STAGES}
    for c in rows:
        cols.setdefault(c.stage, []).append(_out(c))
    return PipelineOut(columns=cols)


@router.post("/sync", response_model=PipelineOut)
async def sync(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> PipelineOut:
    """Pull marketplace events and proposal statuses; move cards; feed outcome memory."""
    mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
    rows = (
        await session.scalars(select(PipelineCard).where(PipelineCard.user_id == user.user_id))
    ).all()
    by_prop = {c.proposal_id: c for c in rows if c.proposal_id}
    try:
        events = await mkt.list_events(int((user.settings_json or {}).get("last_event_id") or 0))
    except MarketplaceError as exc:
        raise HTTPException(503, f"marketplace unavailable: {exc}") from exc
    last_id = int((user.settings_json or {}).get("last_event_id") or 0)
    changed: list[tuple[PipelineCard, str]] = []
    for ev in events:
        last_id = max(last_id, int(ev.event_id)) if str(ev.event_id).isdigit() else last_id
        stage = EVENT_STAGE.get(ev.kind)
        pid = (ev.payload or {}).get("proposal_id")
        card = by_prop.get(pid) if pid else None
        if not card or not stage:
            continue
        if STAGES.index(stage) > STAGES.index(card.stage) if card.stage in STAGES else True:
            card.stage = stage
            card.history = [
                *(card.history or []),
                {"stage": stage, "ts": utcnow().isoformat(), "event": ev.kind},
            ]
            if (ev.payload or {}).get("thread_id"):
                card.marketplace_thread_id = ev.payload["thread_id"]
            changed.append((card, stage))
    st = dict(user.settings_json or {})
    st["last_event_id"] = last_id
    user.settings_json = st
    session.add(user)
    await session.commit()
    for card, stage in changed:
        if stage in ("replied", "interview", "hired", "lost") and not card.outcome_recorded:
            await runtime().record_outcome(user.user_id, card, stage)
            if stage in ("hired", "lost"):
                card.outcome_recorded = True
    await session.commit()
    return await board(user, session)


@router.post("/{card_id}/stage", response_model=PipelineCardOut)
async def move(
    card_id: str,
    body: dict[str, Any],
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PipelineCardOut:
    card = await session.get(PipelineCard, card_id)
    if card is None or card.user_id != user.user_id:
        raise HTTPException(404, "card not found")
    stage = body.get("stage")
    if stage not in STAGES:
        raise HTTPException(400, f"stage must be one of {STAGES}")
    card.stage = stage
    card.history = [
        *(card.history or []),
        {"stage": stage, "ts": utcnow().isoformat(), "event": "manual"},
    ]
    await session.commit()
    if stage in ("replied", "interview", "hired", "lost"):
        await runtime().record_outcome(user.user_id, card, stage)
    return _out(card)
