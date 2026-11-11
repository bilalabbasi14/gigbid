"""Application database: users, settings, saved searches, job cache, runs, pipeline cards,
conversation threads, encrypted OAuth tokens. Async SQLAlchemy over psycopg (SQLite in tests).
Every query that touches user data is scoped by user_id (tenant scoping, E4)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent import settings


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("usr")
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | reviewer | admin
    persona: Mapped[str] = mapped_column(String(32), default="ai_ml")  # persona corpus or "own"
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)  # prefs, autonomy, budgets


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    search_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("srch")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(String(200), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    payment_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    min_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=180)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_posted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class JobRecord(Base):
    """A marketplace job as seen by one user, with the latest analysis snapshot for the inbox."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_user_job"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    job_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_search_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(
        String(24), default="new"
    )  # new | analysing | decided | skipped | watch | drafted | submitted | dismissed
    decision: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    price_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    connects_cost: Mapped[int] = mapped_column(Integer, default=0)
    latest_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Run(Base):
    """One graph thread (bid or conversation). The checkpointer holds the state; this row is the
    index the UI lists and streams from."""

    __tablename__ = "runs"
    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # bid | conversation | portfolio
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    marketplace_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    current_node: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_attention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


Index("ix_runs_user_status", Run.user_id, Run.status)


class PipelineCard(Base):
    __tablename__ = "pipeline_cards"
    card_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("card")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    marketplace_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(
        String(16), default="drafted"
    )  # drafted | submitted | viewed | replied | interview | hired | lost
    bid_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    connects_spent: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome_recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # upwork | github | google
    encrypted: Mapped[str] = mapped_column(Text)  # Fernet token of the JSON payload
    scopes: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ConnectsLedger(Base):
    __tablename__ = "connects_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    job_id: Mapped[str] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PortfolioItem(Base):
    """User-added portfolio material (uploads, builder output) queued for incremental ingestion."""

    __tablename__ = "portfolio_items"
    item_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # cv | case_study | repo | review | proposal
    title: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    ingested_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- engine / session
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _async_url(url: str) -> str:
    if url.startswith("sqlite"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///") if "+aiosqlite" not in url else url
    return url.replace("postgresql://", "postgresql+psycopg://")


def init_engine(url: str | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    url = _async_url(url or settings.env().database_url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True} if not url.startswith("sqlite") else {}
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def create_all() -> None:
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as s:
        yield s


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker
