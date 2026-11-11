"""SQLite schema for the GigSim marketplace simulator."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("GIGSIM_DB_PATH") or str(ROOT / "data/processed/gigsim.db")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"
    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)
    hires: Mapped[int] = mapped_column(Integer, default=0)
    jobs_posted: Mapped[int] = mapped_column(Integer, default=0)
    avg_hourly_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    member_since: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    adversarial: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_prefs: Mapped[dict] = mapped_column(JSON, default=dict)  # never exposed via the API


class Job(Base):
    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.client_id"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    persona_hint: Mapped[str] = mapped_column(String)  # seed bookkeeping only; not served
    payment_type: Mapped[str] = mapped_column(String)  # fixed | hourly
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[str | None] = mapped_column(String, nullable=True)
    screening_questions: Mapped[list] = mapped_column(JSON, default=list)
    connects_cost: Mapped[int] = mapped_column(Integer, default=8)
    applicants: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pool")  # pool | open | closed
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String, default="")
    release_order: Mapped[int] = mapped_column(Integer, default=0)


class Account(Base):
    __tablename__ = "accounts"
    api_key: Mapped[str] = mapped_column(String, primary_key=True)
    freelancer_id: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    connects: Mapped[int] = mapped_column(Integer, default=200)


class Proposal(Base):
    __tablename__ = "proposals"
    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    freelancer_id: Mapped[str] = mapped_column(String)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"))
    cover_letter: Mapped[str] = mapped_column(Text)
    bid_amount: Mapped[float] = mapped_column(Float)
    bid_type: Mapped[str] = mapped_column(String)  # fixed | hourly
    screening_answers: Mapped[list] = mapped_column(JSON, default=list)
    connects_spent: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="submitted")
    # submitted | viewed | replied | interview | hired | lost
    client_decision: Mapped[dict] = mapped_column(JSON, default=dict)  # score breakdown, hidden
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    proposal_id: Mapped[str] = mapped_column(String)
    freelancer_id: Mapped[str] = mapped_column(String)
    sender: Mapped[str] = mapped_column(String)  # client | freelancer
    body: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    freelancer_id: Mapped[str] = mapped_column(String)
    endpoint: Mapped[str] = mapped_column(String)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """Marketplace events the pipeline board consumes (proposal viewed, replied, ...)."""

    __tablename__ = "events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    freelancer_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


def make_engine(path: str | None = None):
    p = path or DB_PATH
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    url = "sqlite://" if p == ":memory:" else f"sqlite:///{p}"
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if p == ":memory:":
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
