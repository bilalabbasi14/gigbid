"""Request and response models for the API (the OpenAPI schema generates the TypeScript client)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from agent.handoffs import (
    ApprovalPayload,
    BidDecision,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    PriceQuote,
    ProposalDraft,
    RiskReport,
)


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    persona: Literal["ai_ml", "fullstack", "data_analyst", "own"] = "ai_ml"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    persona: str
    onboarded: bool
    settings: dict[str, Any]


# ---- settings ----
class UserSettingsIn(BaseModel):
    persona: Literal["ai_ml", "fullstack", "data_analyst", "own"] | None = None
    hourly_rate: float | None = Field(default=None, ge=1)
    hourly_floor: float | None = Field(default=None, ge=1)
    min_project_budget: float | None = Field(default=None, ge=0)
    weekly_connects_budget: int | None = Field(default=None, ge=0)
    autonomy: Literal["manual", "auto_skip"] | None = None
    filters: dict[str, Any] | None = None
    marketplace_mode: Literal["gigsim", "upwork_live"] | None = None
    onboarded: bool | None = None


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=10)
    payment_type: Literal["fixed", "hourly"] | None = None
    min_budget: float | None = None
    interval_minutes: int = Field(default=180, ge=30, le=1440)
    enabled: bool = True


class SavedSearchOut(SavedSearchIn):
    search_id: str
    last_run_at: dt.datetime | None = None


class MemoryView(BaseModel):
    style: list[dict[str, Any]]
    outcome: list[dict[str, Any]]
    candidates: list[dict[str, Any]]


class ConnectedAccount(BaseModel):
    provider: str
    connected: bool
    scopes: str = ""
    expires_at: dt.datetime | None = None


# ---- jobs ----
class JobListItem(BaseModel):
    job_id: str
    title: str
    status: str
    decision: str | None = None
    fit_score: float | None = None
    risk_score: float | None = None
    risk_flags: list[str] = Field(default_factory=list)
    price_amount: float | None = None
    price_type: str | None = None
    connects_cost: int = 0
    payment_type: str | None = None
    budget: float | None = None
    hourly_min: float | None = None
    hourly_max: float | None = None
    posted_at: str | None = None
    first_seen_at: dt.datetime
    latest_thread_id: str | None = None
    recommended_action: str


class JobListOut(BaseModel):
    items: list[JobListItem]
    total: int


class JobDetailOut(BaseModel):
    job: dict[str, Any]
    record: JobListItem
    thread_id: str | None = None
    status: str | None = None
    job_spec: JobSpec | None = None
    risk_report: RiskReport | None = None
    fit_report: FitReport | None = None
    decision: BidDecision | None = None
    price_quote: PriceQuote | None = None
    proposal_draft: ProposalDraft | None = None
    critique: Critique | None = None
    compliance_verdict: ComplianceVerdict | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    needs_attention_reason: str | None = None


class AnalyseOut(BaseModel):
    thread_id: str
    status: str


class ScoutIn(BaseModel):
    query: str | None = None
    skills: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=50)
    analyse: bool = Field(default=False, description="queue a bid-graph run for each new job")


class ScoutOut(BaseModel):
    found: int
    new: int
    queued: list[str]


# ---- approvals ----
class ApprovalItem(BaseModel):
    thread_id: str
    kind: Literal["proposal", "message"]
    job_id: str | None
    title: str
    created_at: dt.datetime
    payload: dict[str, Any]


class ApprovalListOut(BaseModel):
    items: list[ApprovalItem]


class ApprovalDecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_cover_letter: str | None = Field(default=None, max_length=8000)
    edited_answers: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)
    confirmed_slot: dict[str, Any] | None = None


class ApprovalResultOut(BaseModel):
    thread_id: str
    status: str
    submission: dict[str, Any] | None = None
    sent: dict[str, Any] | None = None
    promoted_style_rules: list[str] = Field(default_factory=list)
    next_payload: dict[str, Any] | None = None


class RegenerateIn(BaseModel):
    paragraph_index: int = Field(ge=0)
    instruction: str = Field(default="", max_length=500)


class RegenerateOut(BaseModel):
    paragraph_index: int
    paragraph: str
    cover_letter: str


# ---- runs ----
class RunOut(BaseModel):
    thread_id: str
    kind: str
    job_id: str | None
    status: str
    current_node: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    latency_ms: int | None = None
    cost_usd: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    trace_url: str | None = None
    needs_attention_reason: str | None = None


class RunDetailOut(RunOut):
    trace: list[dict[str, Any]] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)


class ReplayIn(BaseModel):
    checkpoint_id: str


# ---- pipeline / messages ----
class PipelineCardOut(BaseModel):
    card_id: str
    job_id: str
    title: str
    stage: str
    proposal_id: str | None
    marketplace_thread_id: str | None
    bid_thread_id: str | None
    bid_amount: float | None
    bid_type: str | None
    connects_spent: int
    updated_at: dt.datetime
    history: list[dict[str, Any]] = Field(default_factory=list)


class PipelineOut(BaseModel):
    columns: dict[str, list[PipelineCardOut]]


class ThreadOut(BaseModel):
    marketplace_thread_id: str
    job_id: str | None
    job_title: str | None
    status: str | None
    unread: int
    last_message: dict[str, Any] | None
    conversation_thread_id: str | None = None
    pending_approval: bool = False


class MessagesOut(BaseModel):
    marketplace_thread_id: str
    items: list[dict[str, Any]]
    suggested_reply: dict[str, Any] | None = None
    conversation_thread_id: str | None = None


# ---- analytics ----
class AnalyticsOut(BaseModel):
    funnel: dict[str, int]
    by_category: list[dict[str, Any]]
    connects: dict[str, Any]
    cost_latency: dict[str, Any]
    rejection_reasons: list[dict[str, Any]]
    retrieval_results: dict[str, Any] = Field(default_factory=dict)


class HealthOut(BaseModel):
    status: str
    marketplace_mode: str
    marketplace_reachable: bool
    degraded: dict[str, Any]
    policy_version: int
    model_profile: str


__all__ = ["ApprovalPayload"]
