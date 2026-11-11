"""`make demo`: one GigSim job through the full bid graph to the approval gate, then (optionally)
approve from the command line to show the exactly-once submission. Uses the in-process MCP
servers, the real retriever over pgvector and the configured open models.

  uv run python -m scripts.demo --query "machine learning" [--persona ai_ml] [--approve] [--job-id JOB]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.deps import Deps
from agent.graphs.bid_graph import build_bid_graph, initial_state, run_config
from agent.mcp_client import ToolProvider, in_process_loader


def section(title: str) -> None:
    print(f"\n=== {title} ===")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id")
    ap.add_argument("--query", default="machine learning")
    ap.add_argument("--persona", default="ai_ml")
    ap.add_argument(
        "--approve", action="store_true", help="approve at the gate and submit to GigSim"
    )
    ap.add_argument(
        "--postgres", action="store_true", help="use the Postgres checkpointer instead of memory"
    )
    args = ap.parse_args()

    from rag import embeddings

    embeddings.warm()  # load the CPU models once, outside any node timeout
    provider = ToolProvider(loader=in_process_loader)
    deps = Deps(tools=provider)
    job_id = args.job_id
    if not job_id:
        search = await provider.tool("marketplace", "search_jobs")
        found = await search.ainvoke({"query": args.query, "limit": 5})
        if not found["items"]:
            raise SystemExit(f"no open GigSim jobs match {args.query!r}")
        job_id = found["items"][0]["job_id"]

    if args.postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from agent import settings

        url = settings.env().database_url.replace("postgresql+psycopg://", "postgresql://")
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            await run(deps, saver, job_id, args)
    else:
        await run(deps, InMemorySaver(), job_id, args)


async def run(deps: Deps, saver, job_id: str, args) -> None:  # type: ignore[no-untyped-def]
    graph = build_bid_graph(deps, checkpointer=saver)
    thread_id = f"demo-{uuid.uuid4().hex[:8]}"
    cfg = run_config(thread_id)
    prefs = {
        "persona": args.persona,
        "hourly_rate": 55,
        "hourly_floor": 30,
        "min_project_budget": 100,
        "weekly_connects_budget": 80,
    }
    section(f"running bid graph for {job_id} on thread {thread_id}")
    async for event in graph.astream(
        initial_state(job_id, thread_id=thread_id, persona=args.persona, user_prefs=prefs),
        cfg,
        stream_mode="updates",
    ):
        for node, update in event.items():
            if node == "__interrupt__":
                continue
            status = update.get("status", "") if isinstance(update, dict) else ""
            print(f"  [{node:16s}] -> {status}")
    state = await graph.aget_state(cfg)
    values = state.values
    section("analyses")
    print("decision:", json.dumps(values.get("decision"), indent=1))
    print(
        "risk:",
        values.get("risk_report", {}).get("score"),
        values.get("risk_report", {}).get("flags"),
    )
    print(
        "fit:",
        values.get("fit_report", {}).get("score"),
        [
            (m["requirement"][:40], m["strength"])
            for m in values.get("fit_report", {}).get("matrix", [])
        ],
    )
    if "price_quote" in values:
        print(
            "price:",
            values["price_quote"]["amount"],
            values["price_quote"]["bid_type"],
            "|",
            values["price_quote"]["rationale"],
        )
    if "proposal_draft" in values:
        section("draft")
        print(values["proposal_draft"]["cover_letter"])
        print("\nverification:", values["proposal_draft"].get("verification"))
        print(
            "critique:",
            values.get("critique", {}).get("passed"),
            values.get("critique", {}).get("issues"),
        )
        print("compliance:", values.get("compliance_verdict", {}).get("reason"))
    usage = values.get("usage", {})
    print(f"\nstatus={values.get('status')} steps={values.get('steps')} tokens={usage}")
    if values.get("errors"):
        print("errors:", values["errors"])
    if values.get("needs_attention_reason"):
        print("needs attention:", values["needs_attention_reason"])
    if state.next and "approval" in state.next:
        section("waiting for human approval (interrupt)")
        payload = (
            state.tasks[0].interrupts[0].value
            if state.tasks and state.tasks[0].interrupts
            else values.get("approval_payload", {})
        )
        print("dry-run preview:", json.dumps(payload.get("dry_run_preview"), indent=1)[:400])
        if args.approve:
            section("approving -> submit")
            out = await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
            print("submission:", out.get("submission"))
            out2 = await graph.ainvoke(
                Command(resume={"action": "approve"}), cfg
            )  # idempotent re-resume
            print(
                "second resume submission:",
                out2.get("submission"),
                "(same proposal id, nothing spent twice)",
            )
        else:
            print("run again with --approve to submit, or approve from the web UI")


if __name__ == "__main__":
    asyncio.run(main())
