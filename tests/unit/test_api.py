"""API end-to-end with a SQLite database, in-memory checkpointer, fake LLM and fake marketplace:
auth, settings, inbox, analyse -> approval -> submit, pipeline, runs, SSE, analytics."""

from __future__ import annotations

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/processed/test_api.db"
os.environ["GIGBID_IN_PROCESS_MCP"] = "0"
os.environ["GIGBID_WARM_MODELS"] = "0"

from agent import settings  # noqa: E402

settings.reload()

from agent.deps import Deps  # noqa: E402
from agent.marketplace_port import JobSummary, Thread  # noqa: E402
from apps.api import main as api_main  # noqa: E402
from tests.unit.test_bid_graph import JOB, FakeTools, Script  # noqa: E402


class FakeMarket:
    name = "gigsim"

    async def search_jobs(self, query=None, **kw):
        return [
            JobSummary(**{k: v for k, v in JOB.items() if k in JobSummary.model_fields}),
            JobSummary(
                job_id="job_dup",
                title="[Reposted] " + JOB["title"],
                description=JOB["description"],
                payment_type="fixed",
                budget=1200.0,
            ),
        ]

    async def list_threads(self):
        return [Thread(thread_id="thr_1", job_id="job_test_1", job_title=JOB["title"], unread=1)]

    async def list_messages(self, thread_id):
        return []

    async def list_events(self, since_id=0):
        return []

    async def health(self):
        return True

    policy_version = 1

    async def get_policy(self):
        return {"version": self.policy_version}


@pytest.fixture
async def client(monkeypatch, tmp_path):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    settings.reload()
    tools = FakeTools()
    api_main.DEPS_OVERRIDE = Deps(
        tools=tools.provider(),
        invoke=Script(),
        use_reranker=False,
        market_stats={
            "personas": {
                "ai_ml": {
                    "fixed_budget_usd": {"p25": 300, "p50": 600, "p75": 1500},
                    "hourly_min_usd": {"p25": 20, "p50": 35, "p75": 60},
                }
            }
        },
    )
    monkeypatch.setattr("apps.api.routers.jobs.make_marketplace", lambda mode=None: FakeMarket())
    monkeypatch.setattr(
        "apps.api.routers.messages.make_marketplace", lambda mode=None: FakeMarket()
    )
    monkeypatch.setattr(
        "apps.api.routers.pipeline.make_marketplace", lambda mode=None: FakeMarket()
    )
    monkeypatch.setattr("apps.api.main.make_marketplace", lambda mode=None: FakeMarket())
    from apps.api import db

    db._engine = None
    db._sessionmaker = None
    async with api_main.lifespan(api_main.app):
        async with AsyncClient(
            transport=ASGITransport(app=api_main.app), base_url="http://test"
        ) as c:
            c.tools = tools  # type: ignore[attr-defined]
            yield c


async def _wait(c: AsyncClient, thread_id: str, until: set[str], max_wait: float = 20.0) -> dict:
    for _ in range(int(max_wait * 10)):
        r = await c.get(f"/runs/{thread_id}")
        if r.status_code == 200 and r.json()["status"] in until:
            return r.json()
        await asyncio.sleep(0.1)
    raise AssertionError(f"run {thread_id} did not reach {until}")


async def test_auth_and_settings(client: AsyncClient):
    assert (await client.get("/auth/me")).status_code == 401
    r = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "secret123", "persona": "ai_ml"},
    )
    assert r.status_code == 201 and r.json()["persona"] == "ai_ml"
    assert (
        await client.post(
            "/auth/register", json={"email": "a@example.com", "password": "secret123"}
        )
    ).status_code == 409
    me = await client.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"
    r = await client.put(
        "/settings", json={"hourly_rate": 60, "weekly_connects_budget": 40, "onboarded": True}
    )
    assert r.json()["settings"]["hourly_rate"] == 60 and r.json()["onboarded"] is True
    r = await client.post(
        "/settings/searches", json={"name": "RAG jobs", "query": "rag", "skills": ["LangChain"]}
    )
    sid = r.json()["search_id"]
    assert len((await client.get("/settings/searches")).json()) == 1
    assert (await client.delete(f"/settings/searches/{sid}")).status_code == 204
    assert (await client.get("/settings/memory")).json() == {
        "style": [],
        "outcome": [],
        "candidates": [],
    }
    assert (await client.post("/auth/logout")).status_code == 204
    r = await client.post("/auth/login", json={"email": "a@example.com", "password": "wrong"})
    assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "a@example.com", "password": "secret123"})
    assert r.status_code == 200


async def test_inbox_analyse_approve_pipeline(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "b@example.com", "password": "secret123", "persona": "ai_ml"},
    )
    r = await client.post("/jobs/scout", json={"query": "rag", "limit": 10})
    assert (
        r.status_code == 200 and r.json()["found"] == 2 and r.json()["new"] == 1
    )  # duplicate dismissed
    inbox = (await client.get("/jobs")).json()
    assert inbox["total"] == 1 and inbox["items"][0]["recommended_action"] == "analyse"
    r = await client.post("/jobs/job_test_1/analyse")
    assert r.status_code == 202
    thread_id = r.json()["thread_id"]
    run = await _wait(
        client, thread_id, {"awaiting_approval", "needs_attention", "failed", "skipped"}
    )
    assert run["status"] == "awaiting_approval", run
    detail = (await client.get("/jobs/job_test_1")).json()
    assert (
        detail["decision"]["decision"] == "bid"
        and detail["proposal_draft"]["cover_letter"]
        and detail["fit_report"]["matrix"]
    )
    assert detail["record"]["recommended_action"] == "review proposal"
    # SSE on a waiting run returns the snapshot then the interrupt marker
    async with client.stream("GET", f"/runs/{thread_id}/stream") as s:
        body = ""
        async for chunk in s.aiter_text():
            body += chunk
            if "event: interrupt" in body:
                break
        assert "event: snapshot" in body
    pending = (await client.get("/approvals")).json()["items"]
    assert len(pending) == 1 and pending[0]["proposal"]["dry_run_preview"]["connects_cost"] == 8
    one = (await client.get(f"/approvals/{thread_id}")).json()
    assert one["proposal"]["draft"]["cover_letter"]
    # regenerate one paragraph would need a model; the edit path is exercised instead
    edited = one["proposal"]["draft"]["cover_letter"].replace(
        "I keep the stack", "I will keep the stack"
    )
    r = await client.post(
        f"/approvals/{thread_id}", json={"action": "edit", "edited_cover_letter": edited}
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "awaiting_approval"
        and r.json()["next_proposal"]["draft"]["cover_letter"] == edited
    )
    r = await client.post(f"/approvals/{thread_id}", json={"action": "approve"})
    assert (
        r.status_code == 200
        and r.json()["status"] == "submitted"
        and r.json()["submission"]["proposal_id"] == "prop_1"
    )
    assert len(client.tools.submits) == 1  # type: ignore[attr-defined]
    assert (
        await client.post(f"/approvals/{thread_id}", json={"action": "approve"})
    ).status_code == 409  # nothing to resume
    board = (await client.get("/pipeline")).json()["columns"]
    assert len(board["submitted"]) == 1 and board["submitted"][0]["proposal_id"] == "prop_1"
    runs = (await client.get("/runs")).json()
    assert runs[0]["status"] == "submitted" and runs[0]["latency_ms"] is not None
    detail = (await client.get(f"/runs/{thread_id}")).json()
    assert (
        detail["trace"]
        and detail["checkpoints"]
        and detail["state"]["submission"]["proposal_id"] == "prop_1"
    )
    a = (await client.get("/analytics")).json()
    assert a["funnel"]["submitted"] == 1 and a["cost_latency"]["jobs_analysed"] == 1
    assert (await client.get("/jobs")).json()["items"][0]["status"] == "submitted"
    r = await client.post(
        "/pipeline/" + board["submitted"][0]["card_id"] + "/stage", json={"stage": "replied"}
    )
    assert r.json()["stage"] == "replied"


async def test_reject_and_tenant_scoping(client: AsyncClient):
    await client.post("/auth/register", json={"email": "c@example.com", "password": "secret123"})
    await client.post("/jobs/scout", json={"limit": 5})
    thread_id = (await client.post("/jobs/job_test_1/analyse")).json()["thread_id"]
    await _wait(client, thread_id, {"awaiting_approval"})
    r = await client.post(f"/approvals/{thread_id}", json={"action": "reject", "reason": "not now"})
    assert r.json()["status"] == "rejected"
    # another user cannot see this run or job
    await client.post("/auth/logout")
    await client.post("/auth/register", json={"email": "d@example.com", "password": "secret123"})
    assert (await client.get(f"/runs/{thread_id}")).status_code == 404
    assert (await client.get("/jobs/job_test_1")).status_code == 404
    assert (await client.get("/jobs")).json()["total"] == 0


async def test_health_reports_mode(client: AsyncClient):
    h = (await client.get("/health")).json()
    assert (
        h["marketplace_mode"] == "gigsim"
        and "policy_version" in h
        and h["model_profile"] in ("open", "paid", "local")
    )


async def test_health_flags_a_newer_marketplace_policy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    h = (await client.get("/health")).json()
    assert h["marketplace_policy_version"] == 1 and h["policy_drift"] is False
    monkeypatch.setattr(FakeMarket, "policy_version", 2)
    h = (await client.get("/health")).json()
    assert h["marketplace_policy_version"] == 2 and h["policy_drift"] is True
