"""Marketplace MCP server with a fake port: schemas, annotations, idempotency, dry_run,
rate limiting, degraded mode and the audit log. No network."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")

import pytest  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from agent.marketplace_port import (  # noqa: E402
    ClientHistory,
    ConnectsBalance,
    JobSummary,
    MarketplaceUnavailableError,
    Message,
    MessageIn,
    MessageResult,
    ProposalDraftIn,
    ProposalResult,
    Thread,
)
from mcp_servers.common.audit import AuditLog  # noqa: E402
from mcp_servers.common.ratelimit import UserRateLimiter  # noqa: E402
from mcp_servers.marketplace.server import build_server  # noqa: E402

JOB = JobSummary(
    job_id="job_1",
    title="Build a RAG bot",
    description="Need a chatbot. Contact me on WhatsApp +1 415 555 0199",
    skills=["Python"],
    payment_type="fixed",
    budget=500,
    connects_cost=8,
    client_id="cl_1",
)


class FakePort:
    name = "gigsim"

    def __init__(self) -> None:
        self.submitted: dict[str, ProposalResult] = {}
        self.down = False
        self.connects = 100

    async def _check(self):
        if self.down:
            raise MarketplaceUnavailableError(
                "marketplace 503", status=503, retry_after=2, kind="upstream"
            )

    async def search_jobs(self, query=None, **kw):
        await self._check()
        return [JOB]

    async def get_job(self, job_id):
        await self._check()
        return JOB

    async def get_client_history(self, client_id):
        return ClientHistory(client_id=client_id, payment_verified=True, total_spent=1200)

    async def get_connects_balance(self):
        return ConnectsBalance(freelancer_id="f", balance=self.connects)

    async def list_threads(self):
        return [Thread(thread_id="thr_1", job_id="job_1")]

    async def list_messages(self, thread_id):
        return [
            Message(
                message_id="m1",
                thread_id=thread_id,
                sender="client",
                body="Hi, email me at bob@example.com",
            )
        ]

    async def list_events(self, since_id=0):
        return []

    async def get_policy(self):
        return {"version": 1}

    async def health(self):
        return not self.down

    async def create_proposal_draft(self, draft: ProposalDraftIn):
        return ProposalResult(
            job_id=draft.job_id,
            status="draft",
            dry_run=True,
            preview={"connects_cost": 8, "bid_amount": draft.bid_amount},
        )

    async def submit_proposal(self, draft: ProposalDraftIn):
        await self._check()
        if draft.dry_run:
            return ProposalResult(
                job_id=draft.job_id, status="draft", dry_run=True, preview={"connects_cost": 8}
            )
        if draft.idempotency_key in self.submitted:
            r = self.submitted[draft.idempotency_key].model_copy()
            r.idempotent_replay = True
            return r
        self.connects -= 8
        r = ProposalResult(
            proposal_id=f"prop_{len(self.submitted) + 1}",
            job_id=draft.job_id,
            status="submitted",
            connects_spent=8,
            connects_remaining=self.connects,
        )
        self.submitted[draft.idempotency_key] = r
        return r

    async def send_message(self, msg: MessageIn):
        return MessageResult(
            message_id="m2",
            thread_id=msg.thread_id,
            dry_run=msg.dry_run,
            preview={"body": msg.body} if msg.dry_run else None,
        )


@pytest.fixture
def setup(tmp_path):
    port = FakePort()
    audit = AuditLog(path=tmp_path / "audit.jsonl", use_db=False)
    limiter = UserRateLimiter(per_minute=60, burst=5)
    return port, audit, limiter, build_server(port, audit=audit, limiter=limiter)


DRAFT = {
    "job_id": "job_1",
    "cover_letter": "x" * 80,
    "bid_amount": 450.0,
    "bid_type": "fixed",
    "idempotency_key": "idem-key-0001",
}


async def test_tool_inventory_and_annotations(setup):
    _, _, _, server = setup
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {
            "search_jobs",
            "get_job",
            "get_client_history",
            "get_connects_balance",
            "list_threads",
            "list_messages",
            "list_events",
            "marketplace_health",
            "create_proposal_draft",
            "submit_proposal",
            "send_message",
        } == set(tools)
        for name in (
            "search_jobs",
            "get_job",
            "get_client_history",
            "get_connects_balance",
            "list_messages",
        ):
            assert tools[name].annotations.readOnlyHint is True
        assert (
            tools["submit_proposal"].annotations.destructiveHint is True
            and tools["submit_proposal"].annotations.idempotentHint is True
        )
        assert tools["create_proposal_draft"].annotations.destructiveHint is False
        schema = tools["submit_proposal"].inputSchema
        draft_props = (
            schema["$defs"]["ProposalDraftIn"]["properties"]
            if "$defs" in schema
            else schema["properties"]["draft"]["properties"]
        )
        assert (
            draft_props["idempotency_key"]["minLength"] == 8
            and draft_props["cover_letter"]["minLength"] == 50
        )
        assert draft_props["bid_amount"]["exclusiveMinimum"] == 0
        assert all(t.outputSchema for t in tools.values())


async def test_dry_run_then_submit_idempotent(setup):
    port, audit, _, server = setup
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        r = await client.call_tool("submit_proposal", {"draft": {**DRAFT, "dry_run": True}})
        assert (
            r.structuredContent["dry_run"] is True
            and r.structuredContent["preview"]["connects_cost"] == 8
        )
        assert port.connects == 100
        r1 = await client.call_tool("submit_proposal", {"draft": DRAFT})
        assert r1.structuredContent["status"] == "submitted" and port.connects == 92
        r2 = await client.call_tool("submit_proposal", {"draft": DRAFT})
        assert r2.structuredContent["idempotent_replay"] is True and port.connects == 92
        r = await client.call_tool(
            "submit_proposal", {"draft": {**DRAFT, "idempotency_key": "short"}}
        )
        assert r.isError  # schema constraint
    entries = audit.tail(10)
    assert [e["tool"] for e in entries].count("submit_proposal") == 3
    assert all(
        "cover_letter" not in e["args"] for e in entries
    )  # letter body not duplicated into the audit log


async def test_degraded_mode_reports_unavailable(setup):
    port, _, _, server = setup
    port.down = True
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        h = await client.call_tool("marketplace_health", {})
        assert h.structuredContent["reachable"] is False
        r = await client.call_tool("search_jobs", {"query": "rag"})
        assert (
            r.isError
            and "unavailable" in r.content[0].text
            and "Retry after 2" in r.content[0].text
        )


async def test_rate_limit_per_user(setup):
    _, audit, _, server = setup
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        results = [await client.call_tool("get_connects_balance", {}) for _ in range(7)]
        assert sum(1 for r in results if r.isError and "rate limited" in r.content[0].text) >= 2
    assert any(e["result"].get("error") == "rate_limited" for e in audit.tail(10))


async def test_audit_masks_pii(setup):
    _, audit, _, server = setup
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        await client.call_tool("list_messages", {"thread_id": "thr_1"})
        await client.call_tool("get_job", {"job_id": "job_1"})
    text = " ".join(str(e["result"]) for e in audit.tail(5))
    assert "bob@example.com" not in text and "[EMAIL]" in text
    assert "555 0199" not in text and "[PHONE]" in text
