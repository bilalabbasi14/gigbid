"""The single marketplace interface (R1). Two adapters implement it: GigSim and live Upwork.

Everything above this line (MCP marketplace server, Scout, Risk Assessor, Client Liaison) talks
to `MarketplacePort` only. `make_marketplace()` picks the adapter from config.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

PaymentType = Literal["fixed", "hourly"]


class JobSummary(BaseModel):
    job_id: str
    title: str
    description: str
    skills: list[str] = Field(default_factory=list)
    category: str | None = None
    payment_type: PaymentType
    budget: float | None = None
    hourly_min: float | None = None
    hourly_max: float | None = None
    experience_level: str | None = None
    duration: str | None = None
    screening_questions: list[str] = Field(default_factory=list)
    connects_cost: int = 0
    applicants: int | None = None
    posted_at: str | None = None
    client_id: str | None = None
    status: str = "open"
    client: dict[str, Any] | None = None


class ClientHistory(BaseModel):
    client_id: str
    country: str | None = None
    payment_verified: bool | None = None
    total_spent: float | None = None
    rating: float | None = None
    reviews_count: int | None = None
    hires: int | None = None
    jobs_posted: int | None = None
    member_since: str | None = None
    industry: str | None = None
    avg_hourly_paid: float | None = None
    past_jobs: list[dict[str, Any]] = Field(default_factory=list)


class ConnectsBalance(BaseModel):
    freelancer_id: str
    balance: int


class ProposalDraftIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=50, max_length=5000)
    bid_amount: float = Field(gt=0)
    bid_type: PaymentType
    screening_answers: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = False


class ProposalResult(BaseModel):
    proposal_id: str | None = None
    job_id: str
    status: str
    dry_run: bool = False
    preview: dict[str, Any] | None = None
    connects_spent: int = 0
    connects_remaining: int | None = None
    thread_id: str | None = None
    idempotent_replay: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class MessageIn(BaseModel):
    thread_id: str
    body: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = False


class MessageResult(BaseModel):
    message_id: str | None = None
    thread_id: str
    dry_run: bool = False
    preview: dict[str, Any] | None = None
    idempotent_replay: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class Thread(BaseModel):
    thread_id: str
    proposal_id: str | None = None
    job_id: str | None = None
    job_title: str | None = None
    client_id: str | None = None
    status: str | None = None
    unread: int = 0
    last_message: dict[str, Any] | None = None


class Message(BaseModel):
    message_id: str
    thread_id: str
    sender: Literal["client", "freelancer"]
    body: str
    created_at: str | None = None
    read: bool = True


class MarketplaceEvent(BaseModel):
    event_id: int | str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class MarketplaceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        kind: str = "error",
    ) -> None:
        super().__init__(message)
        self.status, self.retry_after, self.kind = status, retry_after, kind


class MarketplaceUnavailableError(MarketplaceError):
    """Transient: rate limited, 5xx, timeout or connection failure. Callers queue and retry."""


class MarketplacePort(Protocol):
    name: str

    async def search_jobs(
        self,
        query: str | None = None,
        *,
        skills: list[str] | None = None,
        payment_type: PaymentType | None = None,
        min_budget: float | None = None,
        posted_after: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[JobSummary]: ...
    async def get_job(self, job_id: str) -> JobSummary: ...
    async def get_client_history(self, client_id: str) -> ClientHistory: ...
    async def get_connects_balance(self) -> ConnectsBalance: ...
    async def list_threads(self) -> list[Thread]: ...
    async def list_messages(self, thread_id: str) -> list[Message]: ...
    async def list_events(self, since_id: int | str = 0) -> list[MarketplaceEvent]: ...
    async def get_policy(self) -> dict[str, Any]: ...
    async def create_proposal_draft(self, draft: ProposalDraftIn) -> ProposalResult: ...
    async def submit_proposal(self, draft: ProposalDraftIn) -> ProposalResult: ...
    async def send_message(self, msg: MessageIn) -> MessageResult: ...
    async def health(self) -> bool: ...


def make_marketplace(mode: str | None = None) -> MarketplacePort:
    from agent import settings

    mode = mode or settings.env().marketplace_mode
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

        return GigSimAdapter()
    if mode == "upwork_live":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter

        return UpworkLiveAdapter()
    raise ValueError(f"unknown MARKETPLACE_MODE {mode!r}")
