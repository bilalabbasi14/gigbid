"""Live Upwork adapter: the official Upwork MCP server (https://mcp.upwork.com/mcp, OAuth 2.1)
mapped onto the MarketplacePort.

Status: implemented against the public tool surface, NOT exercised against a real account (the
author has no Upwork account). Every write creates a draft that the user confirms on Upwork; this
adapter never submits. Reads are scheduled conservatively (agent/config.yaml marketplace.upwork_live).

Tool name mapping is in TOOL_MAP so a rename on Upwork's side is a config-level edit.
"""

from __future__ import annotations

import json
import logging
from typing import Any

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

TOOL_MAP = {
    "search_jobs": "search_jobs",
    "get_job": "get_job_details",
    "get_client": "get_client_details",
    "connects": "get_connects_balance",
    "threads": "list_rooms",
    "messages": "list_messages",
    "draft_proposal": "create_proposal_draft",
    "draft_message": "create_message_draft",
}


class UpworkLiveAdapter:
    name = "upwork_live"

    def __init__(self, user_id: str | None = None, access_token: str | None = None) -> None:
        env = settings.env()
        self.url = env.upwork_mcp_url
        self.user_id = user_id
        self._token = access_token
        self._tools: dict[str, Any] | None = None

    async def _load_tools(self) -> dict[str, Any]:
        if self._tools is not None:
            return self._tools
        if not self._token:
            from apps.api.auth.token_store import load_oauth_token

            self._token = (
                load_oauth_token(self.user_id or "local", "upwork") if self.user_id else None
            )
        if not self._token:
            raise MarketplaceError(
                "Upwork is not connected for this user; complete the OAuth flow in Settings",
                kind="not_connected",
            )
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {
                "upwork": {
                    "transport": "streamable_http",
                    "url": self.url,
                    "headers": {"Authorization": f"Bearer {self._token}"},
                }
            }
        )
        try:
            tools = await client.get_tools(server_name="upwork")
        except Exception as exc:  # noqa: BLE001
            raise MarketplaceUnavailableError(
                f"Upwork MCP unreachable: {exc}", kind="connection"
            ) from exc
        self._tools = {t.name: t for t in tools}
        return self._tools

    async def _call(self, key: str, **args: Any) -> Any:
        tools = await self._load_tools()
        name = TOOL_MAP[key]
        tool = tools.get(name)
        if tool is None:
            raise MarketplaceError(
                f"Upwork MCP server exposes no tool named {name!r} (available: {sorted(tools)})",
                kind="tool_missing",
            )
        try:
            out = await tool.ainvoke(args)
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if any(k in text for k in ("429", "rate", "timeout", "503", "502")):
                raise MarketplaceUnavailableError(str(exc), kind="rate_limited") from exc
            raise MarketplaceError(str(exc)) from exc
        if isinstance(out, str):
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return {"text": out}
        return out

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
        data = await self._call("search_jobs", query=query or " ".join(skills or []), limit=limit)
        items = (
            data.get("jobs") or data.get("items") or data
            if isinstance(data, list)
            else data.get("jobs", [])
        )
        return [self._job(j) for j in items]

    def _job(self, j: dict[str, Any]) -> JobSummary:
        hourly = (j.get("type") or j.get("job_type") or "").lower().startswith("hour") or j.get(
            "hourly_budget"
        ) is not None
        return JobSummary(
            job_id=str(j.get("id") or j.get("job_id") or j.get("ciphertext")),
            title=j.get("title", ""),
            description=j.get("description", ""),
            skills=[s if isinstance(s, str) else s.get("name", "") for s in j.get("skills", [])],
            payment_type="hourly" if hourly else "fixed",
            budget=(j.get("budget") or {}).get("amount")
            if isinstance(j.get("budget"), dict)
            else j.get("budget"),
            hourly_min=(j.get("hourly_budget") or {}).get("min")
            if isinstance(j.get("hourly_budget"), dict)
            else None,
            hourly_max=(j.get("hourly_budget") or {}).get("max")
            if isinstance(j.get("hourly_budget"), dict)
            else None,
            experience_level=j.get("experience_level") or j.get("contractor_tier"),
            duration=j.get("duration"),
            screening_questions=[
                q if isinstance(q, str) else q.get("question", "") for q in j.get("questions", [])
            ],
            connects_cost=int(j.get("connects_required") or j.get("connects_price") or 0),
            posted_at=j.get("created_on") or j.get("posted_at"),
            client_id=str((j.get("client") or {}).get("id") or "") or None,
            client=j.get("client"),
        )

    async def get_job(self, job_id: str) -> JobSummary:
        return self._job(await self._call("get_job", job_id=job_id))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        c = await self._call("get_client", client_id=client_id)
        return ClientHistory(
            client_id=client_id,
            country=c.get("country"),
            payment_verified=c.get("payment_verification_status") == "VERIFIED"
            if c.get("payment_verification_status")
            else c.get("payment_verified"),
            total_spent=c.get("total_spent"),
            rating=c.get("feedback_score") or c.get("rating"),
            reviews_count=c.get("reviews_count"),
            hires=c.get("total_hires"),
            jobs_posted=c.get("total_posted_jobs"),
            member_since=c.get("member_since"),
        )

    async def get_connects_balance(self) -> ConnectsBalance:
        c = await self._call("connects")
        return ConnectsBalance(
            freelancer_id=self.user_id or "me",
            balance=int(c.get("balance") or c.get("connects") or 0),
        )

    async def list_threads(self) -> list[Thread]:
        data = await self._call("threads")
        rooms = data.get("rooms") or data.get("items") or []
        return [
            Thread(
                thread_id=str(r.get("id") or r.get("room_id")),
                job_title=r.get("title") or r.get("topic"),
                unread=int(r.get("unread_count") or 0),
            )
            for r in rooms
        ]

    async def list_messages(self, thread_id: str) -> list[Message]:
        data = await self._call("messages", room_id=thread_id)
        out = []
        for m in data.get("messages") or data.get("items") or []:
            out.append(
                Message(
                    message_id=str(m.get("id")),
                    thread_id=thread_id,
                    sender="freelancer" if m.get("is_mine") or m.get("sender_is_me") else "client",
                    body=m.get("message") or m.get("body") or "",
                    created_at=m.get("created_on"),
                )
            )
        return out

    async def list_events(self, since_id: int | str = 0) -> list[MarketplaceEvent]:
        return []  # Upwork exposes no event feed; the pipeline board is refreshed from proposals/rooms

    async def get_policy(self) -> dict[str, Any]:
        return {
            "version": "upwork-tos",
            "source": "https://www.upwork.com/legal",
            "connects": {"boost_allowed": True},
        }

    async def health(self) -> bool:
        try:
            await self._load_tools()
            return True
        except MarketplaceError:
            return False

    # ---- writes: DRAFTS ONLY on Upwork ----
    async def create_proposal_draft(self, draft: ProposalDraftIn) -> ProposalResult:
        preview = {
            "job_id": draft.job_id,
            "cover_letter": draft.cover_letter,
            "bid_amount": draft.bid_amount,
            "bid_type": draft.bid_type,
            "screening_answers": draft.screening_answers,
            "connects_cost": "shown on Upwork",
        }
        if draft.dry_run:
            return ProposalResult(
                job_id=draft.job_id, status="draft", dry_run=True, preview=preview
            )
        data = await self._call(
            "draft_proposal",
            job_id=draft.job_id,
            cover_letter=draft.cover_letter,
            charge_rate=draft.bid_amount,
            answers=draft.screening_answers,
        )
        return ProposalResult(
            proposal_id=str(data.get("id") or data.get("draft_id") or ""),
            job_id=draft.job_id,
            status="draft_on_upwork",
            preview=preview,
            raw=data if isinstance(data, dict) else {"result": data},
        )

    async def submit_proposal(self, draft: ProposalDraftIn) -> ProposalResult:
        """Upwork requires the user to confirm every proposal on the platform; this creates the draft."""
        return await self.create_proposal_draft(draft)

    async def send_message(self, msg: MessageIn) -> MessageResult:
        preview = {"thread_id": msg.thread_id, "body": msg.body}
        if msg.dry_run:
            return MessageResult(thread_id=msg.thread_id, dry_run=True, preview=preview)
        data = await self._call("draft_message", room_id=msg.thread_id, message=msg.body)
        return MessageResult(
            message_id=str(data.get("id") or ""),
            thread_id=msg.thread_id,
            preview=preview,
            raw=data if isinstance(data, dict) else {"result": data},
        )
