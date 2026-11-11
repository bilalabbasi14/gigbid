"""GigSim adapter: maps the simulator's REST contract onto the MarketplacePort.

Transient failures (429, 5xx, timeouts) raise MarketplaceUnavailableError with retry_after so the
MCP layer and the worker can back off. Bounded retries with jittered backoff happen here, once,
so callers above never retry a write (idempotency keys make the one retry safe).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from agent import settings
from agent.marketplace_port import (
    ClientHistory,
    ConnectsBalance,
    JobSummary,
    MarketplaceError,
    MarketplaceEvent,
    MarketplaceUnavailableError,
    Message,
    MessageIn,
    MessageResult,
    PaymentType,
    ProposalDraftIn,
    ProposalResult,
    Thread,
)

log = logging.getLogger(__name__)


class GigSimAdapter:
    name = "gigsim"

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 15.0,
        retries: int = 3,
    ) -> None:
        env = settings.env()
        self.base_url = (base_url or env.gigsim_base_url).rstrip("/")
        self.token = token or env.gigsim_api_token
        self.timeout = timeout
        self.retries = retries
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        idempotent: bool = True,
    ) -> Any:
        attempts = (
            self.retries if idempotent else 2
        )  # writes: one retry, protected by idempotency_key
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                r = await self._http().request(method, path, params=params, json=json)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last = MarketplaceUnavailableError(
                    f"{type(exc).__name__}: {exc}", kind="connection"
                )
            else:
                if r.status_code in (429, 500, 502, 503, 504):
                    ra = float(r.headers.get("Retry-After", "0") or 0)
                    last = MarketplaceUnavailableError(
                        f"marketplace {r.status_code}",
                        status=r.status_code,
                        retry_after=ra or None,
                        kind="rate_limited" if r.status_code == 429 else "upstream",
                    )
                elif r.status_code >= 400:
                    detail = (
                        r.json().get("detail", r.text)
                        if r.headers.get("content-type", "").startswith("application/json")
                        else r.text
                    )
                    raise MarketplaceError(
                        f"marketplace {r.status_code}: {detail}",
                        status=r.status_code,
                        kind="client_error",
                    )
                else:
                    return r.json()
            wait = (
                last.retry_after
                if isinstance(last, MarketplaceUnavailableError) and last.retry_after
                else 0.5 * 2**attempt
            ) + random.uniform(0, 0.3)  # noqa: S311
            log.warning(
                "gigsim %s %s failed (%s); retry %d/%d in %.1fs",
                method,
                path,
                last,
                attempt + 1,
                attempts,
                wait,
            )
            await asyncio.sleep(wait)
        assert last is not None
        raise last

    # ---- reads ----
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
    ) -> list[JobSummary]:
        params: dict[str, Any] = {"page": page, "limit": min(limit, 50)}
        if query:
            params["q"] = query
        if skills:
            params["skills"] = ",".join(skills)
        if payment_type:
            params["payment_type"] = payment_type
        if min_budget is not None:
            params["min_budget"] = min_budget
        if posted_after:
            params["posted_after"] = posted_after
        data = await self._request("GET", "/jobs", params=params)
        return [JobSummary.model_validate(j) for j in data["items"]]

    async def get_job(self, job_id: str) -> JobSummary:
        return JobSummary.model_validate(await self._request("GET", f"/jobs/{job_id}"))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        return ClientHistory.model_validate(await self._request("GET", f"/clients/{client_id}"))

    async def get_connects_balance(self) -> ConnectsBalance:
        return ConnectsBalance.model_validate(await self._request("GET", "/me/connects"))

    async def list_threads(self) -> list[Thread]:
        data = await self._request("GET", "/threads")
        return [Thread.model_validate(t) for t in data["items"]]

    async def list_messages(self, thread_id: str) -> list[Message]:
        data = await self._request("GET", "/messages", params={"thread_id": thread_id})
        return [Message.model_validate(m) for m in data["items"]]

    async def list_events(self, since_id: int | str = 0) -> list[MarketplaceEvent]:
        data = await self._request("GET", "/events", params={"since_id": since_id})
        return [MarketplaceEvent.model_validate(e) for e in data["items"]]

    async def get_policy(self) -> dict[str, Any]:
        return await self._request("GET", "/policy")

    async def health(self) -> bool:
        try:
            r = await self._http().get("/health", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # ---- writes ----
    async def create_proposal_draft(self, draft: ProposalDraftIn) -> ProposalResult:
        """GigSim has no draft state: a draft is a dry run (the preview of what submit would send)."""
        data = await self._request(
            "POST", "/proposals", json={**draft.model_dump(), "dry_run": True}, idempotent=False
        )
        return ProposalResult(
            job_id=draft.job_id,
            status="draft",
            dry_run=True,
            preview=data.get("would_send"),
            connects_spent=0,
            raw=data,
        )

    async def submit_proposal(self, draft: ProposalDraftIn) -> ProposalResult:
        data = await self._request("POST", "/proposals", json=draft.model_dump(), idempotent=False)
        if data.get("dry_run"):
            return ProposalResult(
                job_id=draft.job_id,
                status="draft",
                dry_run=True,
                preview=data.get("would_send"),
                raw=data,
            )
        p = data["proposal"]
        return ProposalResult(
            proposal_id=p["proposal_id"],
            job_id=p["job_id"],
            status=p["status"],
            connects_spent=p["connects_spent"],
            connects_remaining=data.get("connects_remaining"),
            thread_id=p.get("thread_id"),
            idempotent_replay=bool(data.get("idempotent_replay")),
            raw=data,
        )

    async def send_message(self, msg: MessageIn) -> MessageResult:
        data = await self._request("POST", "/messages", json=msg.model_dump(), idempotent=False)
        if data.get("dry_run"):
            return MessageResult(
                thread_id=msg.thread_id, dry_run=True, preview=data.get("would_send"), raw=data
            )
        return MessageResult(
            message_id=data["message_id"],
            thread_id=data["thread_id"],
            idempotent_replay=bool(data.get("idempotent_replay")),
            raw=data,
        )
