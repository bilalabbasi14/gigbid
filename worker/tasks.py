"""Worker task bodies. The API enqueues `run_bid` / `run_conversation` when a worker is
configured (WORKER_MODE=arq); the cron jobs below do scheduled scouting and pipeline syncing."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select

from agent import settings
from agent.marketplace_port import MarketplaceError, make_marketplace
from agent.nodes.scout import fingerprint
from apps.api import db
from apps.api.db import JobRecord, PipelineCard, Run, SavedSearch, User, session_factory, utcnow
from apps.api.runtime import Runtime

log = logging.getLogger("gigbid.worker")


async def init(ctx: dict[str, Any]) -> None:
    logging.basicConfig(level=settings.env().log_level)
    db.init_engine()
    await db.create_all()
    ctx["runtime"] = await Runtime.create(persistent=True)
    try:
        from rag import embeddings

        embeddings.warm()
    except Exception as exc:  # noqa: BLE001
        log.warning("model warm-up skipped: %s", exc)


async def close(ctx: dict[str, Any]) -> None:
    rt = ctx.get("runtime")
    if rt:
        await rt.close()


def _rt(ctx: dict[str, Any]) -> Runtime:
    return ctx["runtime"]


# ------------------------------------------------------------------ graph runs
async def run_bid(
    ctx: dict[str, Any], user_id: str, job_id: str, *, job: dict[str, Any] | None = None
) -> str:
    """Idempotent: if a non-terminal run already exists for (user, job), reuse it."""
    async with session_factory()() as s:
        user = await s.get(User, user_id)
        if user is None:
            raise ValueError("unknown user")
        existing = await s.scalar(
            select(Run).where(
                Run.user_id == user_id,
                Run.job_id == job_id,
                Run.kind == "bid",
                Run.status.in_(("queued", "running", "awaiting_approval")),
            )
        )
        if existing:
            return existing.thread_id
    return await _rt(ctx).start_bid(user, job_id, job=job, background=False)


async def run_conversation(
    ctx: dict[str, Any], user_id: str, marketplace_thread_id: str, job_id: str | None = None
) -> str:
    async with session_factory()() as s:
        user = await s.get(User, user_id)
        if user is None:
            raise ValueError("unknown user")
        existing = await s.scalar(
            select(Run).where(
                Run.user_id == user_id,
                Run.marketplace_thread_id == marketplace_thread_id,
                Run.kind == "conversation",
                Run.status.in_(("queued", "running", "awaiting_approval")),
            )
        )
        if existing:
            return existing.thread_id
    return await _rt(ctx).start_conversation(
        user, marketplace_thread_id, job_id=job_id, background=False
    )


# ------------------------------------------------------------------ scouting
async def scout_search(ctx: dict[str, Any], search_id: str) -> dict[str, int]:
    """Run one saved search: new jobs -> inbox; analyse unless the user disabled it."""
    async with session_factory()() as s:
        search = await s.get(SavedSearch, search_id)
        if search is None or not search.enabled:
            return {"found": 0, "new": 0}
        user = await s.get(User, search.user_id)
        assert user is not None
        mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
        try:
            jobs = await mkt.search_jobs(
                search.query or None,
                skills=search.skills or None,
                payment_type=search.payment_type,
                min_budget=search.min_budget,
                posted_after=search.last_seen_posted_at,
                limit=50,
            )
        except MarketplaceError as exc:
            log.warning(
                "scout %s: marketplace unavailable (%s); will retry next tick", search_id, exc
            )
            return {"found": 0, "new": 0, "unavailable": 1}
        rows = (await s.scalars(select(JobRecord).where(JobRecord.user_id == user.user_id))).all()
        existing = {r.job_id for r in rows}
        fps = {r.fingerprint for r in rows if r.fingerprint}
        new: list[tuple[str, dict[str, Any]]] = []
        newest = search.last_seen_posted_at
        for j in jobs:
            d = j.model_dump()
            if j.posted_at and (newest is None or j.posted_at > newest):
                newest = j.posted_at
            if j.job_id in existing:
                continue
            fp = fingerprint(d)
            dup = fp in fps
            s.add(
                JobRecord(
                    user_id=user.user_id,
                    job_id=j.job_id,
                    title=j.title,
                    job_json=d,
                    fingerprint=fp,
                    connects_cost=j.connects_cost,
                    source_search_id=search_id,
                    status="dismissed" if dup else "new",
                    decision="skip" if dup else None,
                    risk_flags=["duplicate"] if dup else [],
                )
            )
            fps.add(fp)
            if not dup:
                new.append((j.job_id, d))
        search.last_run_at = utcnow()
        search.last_seen_posted_at = newest
        await s.commit()
    auto = (user.settings_json or {}).get("auto_analyse", True)
    if auto:
        for job_id, d in new:
            try:
                await run_bid(ctx, user.user_id, job_id, job=d)
            except Exception as exc:  # noqa: BLE001
                log.exception("bid run for %s failed: %s", job_id, exc)
    return {"found": len(jobs), "new": len(new)}


async def scout_due_searches(ctx: dict[str, Any]) -> int:
    """Cron: run every enabled saved search whose interval has elapsed (per-mode minimum interval)."""
    cfg = settings.config().marketplace
    n = 0
    async with session_factory()() as s:
        searches = (await s.scalars(select(SavedSearch).where(SavedSearch.enabled.is_(True)))).all()
        users = {u.user_id: u for u in (await s.scalars(select(User))).all()}
    now = utcnow()
    for search in searches:
        user = users.get(search.user_id)
        mode = (user.settings_json or {}).get("marketplace_mode") if user else None
        min_interval = int(
            cfg.get(mode or settings.env().marketplace_mode, {}).get("scout_interval_minutes", 30)
        )
        interval = max(search.interval_minutes, min_interval)
        if search.last_run_at and (now - search.last_run_at) < dt.timedelta(minutes=interval):
            continue
        await scout_search(ctx, search.search_id)
        n += 1
    return n


# ------------------------------------------------------------------ pipeline + conversations
async def sync_pipeline(ctx: dict[str, Any], user_id: str) -> int:
    from apps.api.routers.pipeline import EVENT_STAGE, STAGES

    async with session_factory()() as s:
        user = await s.get(User, user_id)
        if user is None:
            return 0
        mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
        try:
            events = await mkt.list_events(
                int((user.settings_json or {}).get("last_event_id") or 0)
            )
        except MarketplaceError:
            return 0
        cards = {
            c.proposal_id: c
            for c in (
                await s.scalars(select(PipelineCard).where(PipelineCard.user_id == user_id))
            ).all()
            if c.proposal_id
        }
        last_id = int((user.settings_json or {}).get("last_event_id") or 0)
        moved = []
        for ev in events:
            if str(ev.event_id).isdigit():
                last_id = max(last_id, int(ev.event_id))
            stage = EVENT_STAGE.get(ev.kind)
            card = cards.get((ev.payload or {}).get("proposal_id"))
            if (
                not card
                or not stage
                or (card.stage in STAGES and STAGES.index(stage) <= STAGES.index(card.stage))
            ):
                continue
            card.stage = stage
            card.history = [
                *(card.history or []),
                {"stage": stage, "ts": utcnow().isoformat(), "event": ev.kind},
            ]
            if (ev.payload or {}).get("thread_id"):
                card.marketplace_thread_id = ev.payload["thread_id"]
            moved.append((card, stage))
        st = dict(user.settings_json or {})
        st["last_event_id"] = last_id
        user.settings_json = st
        s.add(user)
        await s.commit()
        for card, stage in moved:
            if stage in ("replied", "interview", "hired", "lost"):
                await _rt(ctx).record_outcome(user_id, card, stage)
        return len(moved)


async def sync_all_pipelines(ctx: dict[str, Any]) -> int:
    async with session_factory()() as s:
        ids = [u.user_id for u in (await s.scalars(select(User))).all()]
    return sum([await sync_pipeline(ctx, uid) for uid in ids])


async def poll_conversations(ctx: dict[str, Any]) -> int:
    """Cron: for every thread with unread client messages, draft a reply for approval."""
    n = 0
    async with session_factory()() as s:
        users = (await s.scalars(select(User))).all()
    for user in users:
        mkt = make_marketplace((user.settings_json or {}).get("marketplace_mode"))
        try:
            threads = await mkt.list_threads()
        except MarketplaceError:
            continue
        for t in threads:
            if t.unread:
                await run_conversation(ctx, user.user_id, t.thread_id, job_id=t.job_id)
                n += 1
    return n


# ------------------------------------------------------------------ portfolio ingestion
async def ingest_portfolio(ctx: dict[str, Any], persona: str) -> dict[str, int]:
    """Incremental re-index after the user adds material (runs here, never in a request)."""
    import asyncio

    from rag.index.pg import ChunkStore
    from rag.ingest.cli import PERSONAS_ROOT, ingest_persona

    return await asyncio.to_thread(lambda: ingest_persona(ChunkStore(), PERSONAS_ROOT / persona))
