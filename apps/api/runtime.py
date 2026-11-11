"""Graph runtime shared by the API and the worker: checkpointer, store, deps, compiled graphs,
and the functions that start, stream and resume runs while keeping the index tables in sync."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import time
import uuid
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from sqlalchemy import select

from agent import settings
from agent.deps import Deps
from agent.graphs.bid_graph import build_bid_graph, initial_state, run_config
from agent.graphs.conversation_graph import (
    build_conversation_graph,
    conversation_config,
    initial_conversation_state,
)
from agent.graphs.portfolio_builder_graph import build_graph as build_portfolio_graph
from agent.graphs.portfolio_builder_graph import builder_config, initial_builder_state
from agent.memory import promotion_rules
from agent.memory import store as memstore
from agent.memory.promotion_rules import proposal_features
from apps.api.bus import bus
from apps.api.db import JobRecord, PipelineCard, Run, User, session_factory, utcnow

log = logging.getLogger(__name__)
TERMINAL = {"submitted", "skipped", "watch", "rejected", "blocked", "needs_attention", "failed"}

# rough open-model prices per 1M tokens for cost accounting (USD); hosted open providers
PRICE_PER_M = {"input": 0.15, "output": 0.60}


def cost_usd(usage: dict[str, Any]) -> float:
    return round(
        (
            usage.get("input_tokens", 0) * PRICE_PER_M["input"]
            + usage.get("output_tokens", 0) * PRICE_PER_M["output"]
        )
        / 1_000_000,
        5,
    )


class Runtime:
    def __init__(
        self,
        deps: Deps | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
    ) -> None:
        self.deps = deps or Deps()
        self.checkpointer = checkpointer or InMemorySaver()
        self.store = store or InMemoryStore()
        memstore.set_store(self.store)
        self.bid_graph = build_bid_graph(
            self.deps, checkpointer=self.checkpointer, store=self.store
        )
        self.portfolio_graph = build_portfolio_graph(self.deps, checkpointer=self.checkpointer)
        self.conv_graph = build_conversation_graph(
            self.deps, checkpointer=self.checkpointer, store=self.store
        )
        self._tasks: set[asyncio.Task[Any]] = set()
        self.persistence = "memory"
        self._cm: list[Any] = []

    # ------------------------------------------------------------ lifecycle
    @classmethod
    async def create(cls, deps: Deps | None = None, *, persistent: bool = True) -> Runtime:
        checkpointer: BaseCheckpointSaver | None = None
        store: BaseStore | None = None
        cms: list[Any] = []
        if persistent:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from langgraph.store.postgres.aio import AsyncPostgresStore

                url = settings.env().database_url.replace("postgresql+psycopg://", "postgresql://")
                cm1 = AsyncPostgresSaver.from_conn_string(url)
                checkpointer = await cm1.__aenter__()
                await checkpointer.setup()
                cm2 = AsyncPostgresStore.from_conn_string(url)
                store = await cm2.__aenter__()
                await store.setup()
                cms = [cm1, cm2]
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Postgres checkpointer unavailable (%s); using in-memory persistence", exc
                )
                checkpointer, store, cms = None, None, []
        rt = cls(deps, checkpointer, store)
        rt._cm = cms
        rt.persistence = "postgres" if cms else "memory"
        return rt

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for cm in reversed(self._cm):
            with contextlib.suppress(Exception):
                await cm.__aexit__(None, None, None)

    # ------------------------------------------------------------ helpers
    def _gc(self, kind: str, thread_id: str, user_id: str) -> tuple[Any, dict[str, Any]]:
        """The compiled graph and run config for a thread of this kind."""
        if kind == "bid":
            return self.bid_graph, run_config(thread_id, user_id=user_id)
        if kind == "portfolio":
            return self.portfolio_graph, builder_config(thread_id, user_id=user_id)
        return self.conv_graph, conversation_config(thread_id, user_id=user_id)

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _update_run(self, thread_id: str, **fields: Any) -> None:
        async with session_factory()() as s:
            run = await s.get(Run, thread_id)
            if run is None:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            await s.commit()

    def user_prefs(self, user: User) -> dict[str, Any]:
        st = dict(user.settings_json or {})
        st.setdefault("persona", user.persona)
        return st

    # ------------------------------------------------------------ bid runs
    async def start_bid(
        self, user: User, job_id: str, *, job: dict[str, Any] | None = None, background: bool = True
    ) -> str:
        thread_id = f"bid-{uuid.uuid4().hex[:12]}"
        async with session_factory()() as s:
            s.add(
                Run(
                    thread_id=thread_id,
                    user_id=user.user_id,
                    kind="bid",
                    job_id=job_id,
                    status="queued",
                )
            )
            rec = await s.scalar(
                select(JobRecord).where(
                    JobRecord.user_id == user.user_id, JobRecord.job_id == job_id
                )
            )
            if rec:
                rec.status, rec.latest_thread_id = "analysing", thread_id
            await s.commit()
        persona = user.persona if user.persona != "own" else f"user_{user.user_id}"
        state = initial_state(
            job_id,
            thread_id=thread_id,
            user_id=user.user_id,
            persona=persona,
            user_prefs=self.user_prefs(user),
            job=job,
            style_rules=memstore.style_rules(user.user_id, self.store),
            outcome_hints=memstore.outcome_hints(user.user_id, None, self.store),
        )
        coro = self._execute(
            thread_id,
            user.user_id,
            self.bid_graph,
            state,
            run_config(thread_id, user_id=user.user_id),
            kind="bid",
        )
        if background:
            self._spawn(coro)
        else:
            await coro
        return thread_id

    async def start_conversation(
        self,
        user: User,
        marketplace_thread_id: str,
        *,
        job_id: str | None = None,
        background: bool = True,
    ) -> str:
        thread_id = f"conv-{uuid.uuid4().hex[:12]}"
        async with session_factory()() as s:
            s.add(
                Run(
                    thread_id=thread_id,
                    user_id=user.user_id,
                    kind="conversation",
                    job_id=job_id,
                    marketplace_thread_id=marketplace_thread_id,
                    status="queued",
                )
            )
            await s.commit()
        state = initial_conversation_state(
            thread_id=thread_id,
            marketplace_thread_id=marketplace_thread_id,
            user_id=user.user_id,
            persona=user.persona,
            job_id=job_id,
            style_rules=memstore.style_rules(user.user_id, self.store),
        )
        coro = self._execute(
            thread_id,
            user.user_id,
            self.conv_graph,
            state,
            conversation_config(thread_id, user_id=user.user_id),
            kind="conversation",
        )
        if background:
            self._spawn(coro)
        else:
            await coro
        return thread_id

    async def start_portfolio_build(
        self,
        user: User,
        *,
        owner: str,
        source_kind: str,
        local_root: str | None = None,
        max_repos: int = 6,
        github_token: str | None = None,
    ) -> str:
        """X3: build verified case studies from a GitHub account (or the demo repositories)."""
        thread_id = f"pf-{uuid.uuid4().hex[:12]}"
        async with session_factory()() as s:
            s.add(Run(thread_id=thread_id, user_id=user.user_id, kind="portfolio", status="queued"))
            await s.commit()
        deps = self.deps
        if source_kind == "github":
            from agent.mcp_client import ToolProvider, github_tool_loader

            deps = Deps(
                tools=ToolProvider(loader=github_tool_loader(github_token or "")),
                invoke=self.deps.invoke,
                use_reranker=self.deps.use_reranker,
            )
        graph = build_portfolio_graph(deps, checkpointer=self.checkpointer)
        state = initial_builder_state(
            thread_id=thread_id,
            owner=owner,
            persona_key=f"user_{user.user_id}",
            user_id=user.user_id,
            source_kind=source_kind,
            local_root=local_root,
            max_repos=max_repos,
        )
        self._spawn(
            self._execute(
                thread_id,
                user.user_id,
                graph,
                state,
                builder_config(thread_id, user_id=user.user_id),
                kind="portfolio",
            )
        )
        return thread_id

    async def _execute(
        self, thread_id: str, user_id: str, graph: Any, inp: Any, cfg: dict[str, Any], *, kind: str
    ) -> dict[str, Any]:
        b = bus()
        t0 = time.perf_counter()
        await self._update_run(thread_id, status="running", started_at=utcnow())
        await b.publish(thread_id, {"type": "status", "status": "running", "ts": time.time()})
        values: dict[str, Any] = {}
        try:
            async for mode, chunk in graph.astream(inp, cfg, stream_mode=["updates", "custom"]):
                if mode == "updates" and isinstance(chunk, dict):
                    for node, update in chunk.items():
                        if node == "__interrupt__":
                            payload = update[0].value if update else {}
                            await b.publish(
                                thread_id,
                                {
                                    "type": "interrupt",
                                    "node": "approval",
                                    "payload_kind": payload.get("kind"),
                                    "ts": time.time(),
                                },
                            )
                            continue
                        status = update.get("status") if isinstance(update, dict) else None
                        # progress only: the run's real status is written once at the end, after
                        # the inbox and pipeline records are synced, so readers never see
                        # "awaiting_approval" (or "submitted") ahead of the records behind it
                        await self._update_run(thread_id, current_node=node, status="running")
                        await b.publish(
                            thread_id,
                            {
                                "type": "node",
                                "node": node,
                                "status": status,
                                "ts": time.time(),
                                "summary": _summary(node, update),
                            },
                        )
                elif mode == "custom":
                    await b.publish(thread_id, {"type": "custom", "data": chunk, "ts": time.time()})
        except Exception as exc:  # noqa: BLE001
            log.exception("run %s failed", thread_id)
            await self._update_run(
                thread_id, status="failed", error=str(exc)[:500], finished_at=utcnow()
            )
            await b.publish(
                thread_id, {"type": "error", "error": str(exc)[:500], "ts": time.time()}
            )
            return {}
        state = await graph.aget_state(cfg)
        values = state.values
        status = values.get("status", "running")
        waiting = bool(state.next) and any("approval" in n for n in state.next)
        if waiting:
            status = "awaiting_approval"
        latency = int((time.perf_counter() - t0) * 1000)
        usage = values.get("usage", {}) or {}
        await self._sync_job_record(user_id, values, thread_id, kind)
        if status == "submitted":
            await self._on_submitted(user_id, values, thread_id, kind)
        await self._update_run(
            thread_id,
            status=status,
            usage_json=usage,
            cost_usd=cost_usd(usage),
            latency_ms=latency,
            needs_attention_reason=values.get("needs_attention_reason"),
            finished_at=None if waiting else utcnow(),
            trace_url=_trace_url(thread_id),
        )
        await b.publish(
            thread_id,
            {"type": "interrupt" if waiting else "done", "status": status, "ts": time.time()},
        )
        return values

    async def resume(
        self, thread_id: str, user_id: str, decision: dict[str, Any]
    ) -> dict[str, Any]:
        async with session_factory()() as s:
            run = await s.get(Run, thread_id)
            if run is None or run.user_id != user_id:
                raise LookupError("run not found")
            kind = run.kind
        graph, cfg = self._gc(kind, thread_id, user_id)
        state = await graph.aget_state(cfg)
        if not state.next:
            raise ValueError("run is not waiting for approval")
        before = (state.values.get("proposal_draft") or state.values.get("reply_draft") or {}).get(
            "cover_letter" if kind == "bid" else "body", ""
        )
        promoted: list[str] = []
        if decision.get("action") == "edit" and decision.get("edited_cover_letter") and before:
            promoted = promotion_rules.record_edit(
                user_id,
                before,
                decision["edited_cover_letter"],
                job_category=state.values.get("persona"),
                store=self.store,
            )
        resume_value: Any = decision
        if kind == "portfolio":
            resume_value = {"decisions": decision.get("portfolio_decisions") or {}}
        values = await self._execute(
            thread_id, user_id, graph, Command(resume=resume_value), cfg, kind=kind
        )
        values["_promoted_style_rules"] = promoted
        return values

    # ------------------------------------------------------------ index tables
    async def _sync_job_record(
        self, user_id: str, values: dict[str, Any], thread_id: str, kind: str
    ) -> None:
        if kind != "bid" or not values.get("job_id"):
            return
        async with session_factory()() as s:
            rec = await s.scalar(
                select(JobRecord).where(
                    JobRecord.user_id == user_id, JobRecord.job_id == values["job_id"]
                )
            )
            job = values.get("job") or {}
            if rec is None:
                rec = JobRecord(
                    user_id=user_id,
                    job_id=values["job_id"],
                    title=job.get("title", values["job_id"]),
                    job_json=job,
                    fingerprint=job.get("fingerprint"),
                )
                s.add(rec)
            if job:
                rec.job_json, rec.title, rec.fingerprint = (
                    job,
                    job.get("title", rec.title),
                    job.get("fingerprint", rec.fingerprint),
                )
            d = values.get("decision") or {}
            rec.decision = d.get("decision")
            rec.fit_score = (values.get("fit_report") or {}).get("score")
            rec.risk_score = (values.get("risk_report") or {}).get("score")
            rec.risk_flags = (values.get("risk_report") or {}).get("flags", [])
            pq = values.get("price_quote") or {}
            rec.price_amount, rec.price_type = pq.get("amount"), pq.get("bid_type")
            rec.connects_cost = int(job.get("connects_cost") or pq.get("connects_cost") or 0)
            rec.latest_thread_id = thread_id
            st = values.get("status", "")
            rec.status = {
                "awaiting_approval": "drafted",
                "submitted": "submitted",
                "skipped": "skipped",
                "watch": "watch",
                "rejected": "decided",
                "blocked": "decided",
                "needs_attention": "decided",
            }.get(st, "decided" if d else "analysing")
            await s.commit()

    async def _on_submitted(
        self, user_id: str, values: dict[str, Any], thread_id: str, kind: str
    ) -> None:
        if kind != "bid":
            return
        sub = values.get("submission") or {}
        job = values.get("job") or {}
        pq = values.get("price_quote") or {}
        async with session_factory()() as s:
            card = await s.scalar(
                select(PipelineCard).where(
                    PipelineCard.user_id == user_id, PipelineCard.job_id == values["job_id"]
                )
            )
            if card is None:
                card = PipelineCard(
                    user_id=user_id,
                    job_id=values["job_id"],
                    title=job.get("title", values["job_id"]),
                )
                s.add(card)
            card.proposal_id = sub.get("proposal_id")
            card.marketplace_thread_id = sub.get("thread_id")
            card.bid_thread_id = thread_id
            card.bid_amount, card.bid_type = pq.get("amount"), pq.get("bid_type")
            card.connects_spent = int(sub.get("connects_spent") or 0)
            card.category = values.get("persona")
            stage = (
                sub.get("status")
                if sub.get("status")
                in ("submitted", "viewed", "replied", "interview", "hired", "lost")
                else "submitted"
            )
            card.stage = stage
            card.history = [*(card.history or []), {"stage": stage, "ts": utcnow().isoformat()}]
            await s.commit()

    async def record_outcome(self, user_id: str, card: PipelineCard, stage: str) -> list[str]:
        """Called by pipeline sync when a card reaches a terminal-ish stage: feed outcome memory."""
        if card.outcome_recorded or not card.bid_thread_id:
            return []
        state = await self.bid_graph.aget_state(run_config(card.bid_thread_id, user_id=user_id))
        v = state.values
        if not v.get("proposal_draft"):
            return []
        feats = proposal_features(v["proposal_draft"], v.get("job", {}), v.get("price_quote"))
        return promotion_rules.record_outcome(
            user_id,
            category=card.category or v.get("persona", "all"),
            features=feats,
            outcome=stage,
            store=self.store,
        )

    # ------------------------------------------------------------ reads
    async def state_values(
        self, thread_id: str, kind: str, user_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        graph, cfg = self._gc(kind, thread_id, user_id)
        st = await graph.aget_state(cfg)
        return st.values, list(st.next or [])

    async def pending_payload(
        self, thread_id: str, kind: str, user_id: str
    ) -> dict[str, Any] | None:
        graph, cfg = self._gc(kind, thread_id, user_id)
        st = await graph.aget_state(cfg)
        for task in st.tasks:
            for intr in getattr(task, "interrupts", []) or []:
                return intr.value
        if st.next and kind == "bid" and st.values.get("approval_payload"):
            return st.values["approval_payload"]
        return None

    async def history(
        self, thread_id: str, kind: str, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        graph, cfg = self._gc(kind, thread_id, user_id)
        out = []
        async for snap in graph.aget_state_history(cfg):
            out.append(
                {
                    "checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
                    "next": list(snap.next or []),
                    "status": snap.values.get("status"),
                    "steps": snap.values.get("steps"),
                    "created_at": snap.created_at,
                    "source": (snap.metadata or {}).get("source"),
                    "node": ((snap.metadata or {}).get("writes") or {}).keys().__iter__().__next__()
                    if (snap.metadata or {}).get("writes")
                    else None,
                }
            )
            if len(out) >= limit:
                break
        return out

    async def replay(self, thread_id: str, kind: str, user: User, checkpoint_id: str) -> str:
        """Fork a new thread from a past checkpoint and run it forward (time travel)."""
        graph, src_cfg = self._gc(kind, thread_id, user.user_id)
        src_cfg = {
            **src_cfg,
            "configurable": {**src_cfg["configurable"], "checkpoint_id": checkpoint_id},
        }
        snap = await graph.aget_state(src_cfg)
        new_thread = f"{kind[:4]}-replay-{uuid.uuid4().hex[:8]}"
        async with session_factory()() as s:
            s.add(
                Run(
                    thread_id=new_thread,
                    user_id=user.user_id,
                    kind=kind,
                    job_id=snap.values.get("job_id"),
                    status="queued",
                )
            )
            await s.commit()
        values = {**snap.values, "thread_id": new_thread, "trace": [], "errors": []}
        _, cfg = self._gc(kind, new_thread, user.user_id)
        # seed the new thread with the old values at the same position, then continue
        await graph.aupdate_state(
            cfg,
            values,
            as_node=(list(snap.next)[0] if snap.next else None)
            and _prev_node(graph, list(snap.next)[0]),
        )
        self._spawn(self._execute(new_thread, user.user_id, graph, None, cfg, kind=kind))
        return new_thread


def _prev_node(graph: Any, next_node: str) -> str | None:
    edges = graph.get_graph().edges
    for e in edges:
        if e.target == next_node and e.source not in ("__start__",):
            return e.source
    return None


def _summary(node: str, update: Any) -> dict[str, Any]:
    if not isinstance(update, dict):
        return {}
    out: dict[str, Any] = {}
    if "decision" in update:
        out["decision"] = update["decision"].get("decision")
        out["reasons"] = update["decision"].get("reasons", [])[:2]
    if "risk_report" in update:
        out["risk"] = update["risk_report"].get("score")
    if "fit_report" in update:
        out["fit"] = update["fit_report"].get("score")
    if "price_quote" in update:
        out["price"] = update["price_quote"].get("amount")
    if "critique" in update:
        out["critique_passed"] = update["critique"].get("passed")
    if "compliance_verdict" in update:
        out["compliance"] = update["compliance_verdict"].get("reason")
    if "proposal_draft" in update:
        out["words"] = update["proposal_draft"].get("word_count")
        out["verification"] = update["proposal_draft"].get("verification")
    if "usage" in update:
        out["usage"] = update["usage"]
    if "needs_attention_reason" in update:
        out["needs_attention"] = update["needs_attention_reason"]
    return out


def _trace_url(thread_id: str) -> str | None:
    env = settings.env()
    if env.langsmith_tracing and env.langsmith_api_key:
        return f"https://smith.langchain.com/projects/p/{env.langsmith_project}?searchModel=%7B%22filter%22%3A%22and(eq(metadata_key%2C%20%5C%22thread_id%5C%22)%2C%20eq(metadata_value%2C%20%5C%22{thread_id}%5C%22))%22%7D"
    return None


RUNTIME: Runtime | None = None


def runtime() -> Runtime:
    assert RUNTIME is not None, "runtime not initialised"
    return RUNTIME


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
