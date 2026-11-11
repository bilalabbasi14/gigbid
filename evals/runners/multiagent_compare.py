"""R&D question C: is the multi-agent design worth it?

Same dev jobs, same MCP tools, same models, three systems:
  (a) single  - one ReAct agent (langchain create_agent) holding every tool
  (b) supervisor - langgraph-supervisor with job reader, risk checker, evidence researcher and writer
  (c) graph   - GigBid's hand-built bid graph (parallel analysis, rules, verifier, critic, compliance)

One evaluator scores every system's FINAL output the same way: bid-or-skip accuracy against gold,
scam recall, unsupported claims in the proposal (claim verifier over the job's top retrieved
evidence plus whatever the system cited), compliance violations left in the output and caught by
a guard, GigSim reply rate when the proposal is submitted to the simulator, tokens and latency.

Results are appended per (system, job) to evals/results/multiagent_rows.jsonl, so the run resumes
across the free-tier daily quota.

  uv run python -m evals.runners.multiagent_compare --jobs 50 [--systems single,supervisor,graph] [--gigsim]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from agent import llm, settings
from agent.marketplace_port import ProposalDraftIn
from agent.nodes.compliance import check_text
from agent.prompts import load_sections
from evals.runners.harness import (
    QuotaGuard,
    RowLog,
    analyse,
    cost,
    draft,
    make_deps,
    sample_jobs,
    summary_stats,
    write_result,
)
from rag.retriever import build_retriever
from rag.verify import unsupported_rate, verify_claims

PREFS = {"floor": 20, "min_budget": 50}


def parse_json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def usage_of(messages: list[Any]) -> dict[str, int]:
    u = {"input_tokens": 0, "output_tokens": 0}
    for m in messages:
        meta = getattr(m, "usage_metadata", None) or {}
        u["input_tokens"] += int(meta.get("input_tokens", 0))
        u["output_tokens"] += int(meta.get("output_tokens", 0))
    return u


async def job_tools(deps, persona: str) -> list[StructuredTool]:  # type: ignore[no-untyped-def]
    """The marketplace and portfolio tools, with the persona fixed so baselines search the right corpus."""
    t = {x.name: x for x in await deps.tools.tools_for("single_agent")}

    async def get_job(job_id: str) -> Any:
        """Fetch one job post by id: description, skills, budget, screening questions, Connects cost, client summary."""
        return await t["get_job"].ainvoke({"job_id": job_id})

    async def get_client_history(client_id: str) -> Any:
        """Public client history by client id: spend, hires, rating, payment verification, past jobs."""
        return await t["get_client_history"].ainvoke({"client_id": client_id})

    async def search_evidence(requirement: str, k: int = 5) -> Any:
        """Search the freelancer's portfolio for evidence supporting one requirement. Returns evidence ids, titles, excerpts."""
        return await t["search_evidence"].ainvoke(
            {"requirement": requirement, "k": k, "persona": persona}
        )

    async def get_case_study(id: str) -> Any:  # noqa: A002 - mirrors the MCP tool's argument name
        """Open one portfolio project (p01, p02, ...) in full."""
        return await t["get_case_study"].ainvoke({"id": id, "persona": persona})

    return [
        StructuredTool.from_function(coroutine=f)
        for f in (get_job, get_client_history, search_evidence, get_case_study)
    ]


async def run_single(row: dict[str, Any], deps) -> tuple[dict[str, Any], dict[str, int]]:  # type: ignore[no-untyped-def]
    from langchain.agents import create_agent

    sec = load_sections("baseline_single_agent")
    tools = await job_tools(deps, row["persona"])
    agent = create_agent(
        llm.chat_for_node("writer", max_tokens=1500, max_retries=4),
        tools=tools,
        system_prompt=sec["system"].replace("{{", "{").replace("}}", "}"),
    )
    out = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=sec["user"].format(
                        persona=row["persona"],
                        floor=PREFS["floor"],
                        min_budget=PREFS["min_budget"],
                        job_id=row["job_id"],
                    )
                )
            ]
        },
        {"recursion_limit": 24},
    )
    msgs = out["messages"]
    final = next((m.content for m in reversed(msgs) if isinstance(m, AIMessage) and m.content), "")
    return parse_json(str(final)), usage_of(msgs)


async def run_supervisor(row: dict[str, Any], deps) -> tuple[dict[str, Any], dict[str, int]]:  # type: ignore[no-untyped-def]
    from langchain.agents import create_agent
    from langgraph_supervisor import create_supervisor

    sec = load_sections("baseline_supervisor")
    tools = {t.name: t for t in await job_tools(deps, row["persona"])}
    medium = llm.chat_for_node("analyst", max_tokens=1200, max_retries=4)
    workers = [
        create_agent(
            medium,
            tools=[tools["get_job"]],
            system_prompt=sec["worker_job_reader"],
            name="job_reader",
        ),
        create_agent(
            llm.chat_for_node("risk_assessor", max_tokens=800, max_retries=4),
            tools=[tools["get_client_history"], tools["get_job"]],
            system_prompt=sec["worker_risk_checker"],
            name="risk_checker",
        ),
        create_agent(
            medium,
            tools=[tools["search_evidence"], tools["get_case_study"]],
            system_prompt=sec["worker_evidence_researcher"],
            name="evidence_researcher",
        ),
        create_agent(
            llm.chat_for_node("writer", max_tokens=1500, max_retries=4),
            tools=[tools["search_evidence"]],
            system_prompt=sec["worker_proposal_writer"],
            name="proposal_writer",
        ),
    ]
    app = create_supervisor(
        workers,
        model=llm.chat_for_node("critic", max_tokens=1500, max_retries=4),
        prompt=sec["system"].replace("{{", "{").replace("}}", "}"),
        output_mode="last_message",
    ).compile()
    out = await app.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=sec["user"].format(
                        persona=row["persona"],
                        floor=PREFS["floor"],
                        min_budget=PREFS["min_budget"],
                        job_id=row["job_id"],
                    )
                )
            ]
        },
        {"recursion_limit": 40},
    )
    msgs = out["messages"]
    final = next(
        (
            m.content
            for m in reversed(msgs)
            if isinstance(m, AIMessage) and m.content and "{" in str(m.content)
        ),
        "",
    )
    return parse_json(str(final)), usage_of(msgs)


async def run_graph(
    row: dict[str, Any], deps
) -> tuple[dict[str, Any], dict[str, int], dict[str, Any]]:  # type: ignore[no-untyped-def]
    st, _ = await analyse(row, deps)
    d = st.get("decision", {}).get("decision")
    out: dict[str, Any] = {
        "decision": "bid" if d == "bid" else "skip",
        "reasons": st.get("decision", {}).get("reasons", []),
        "scam": bool(st.get("risk_report", {}).get("scam_likely")),
        "injection_detected": bool(st.get("risk_report", {}).get("injection_detected")),
    }
    extra: dict[str, Any] = {}
    if d == "bid" and st.get("status") != "skipped":
        st, _ = await draft(st, deps)
        pd = st.get("proposal_draft", {})
        out.update(
            {
                "cover_letter": pd.get("cover_letter"),
                "evidence_ids": pd.get("evidence_ids", []),
                "bid_amount": st.get("price_quote", {}).get("amount"),
            }
        )
        verdict = st.get("compliance_verdict") or {}
        extra = {
            "guard_caught": len(verdict.get("violations", [])),
            "blocked": not verdict.get("allowed", True),
            "bid_type": st.get("price_quote", {}).get("bid_type"),
        }
    return out, st.get("usage", {}), extra


async def evaluate(row: dict[str, Any], out: dict[str, Any], retriever) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """The shared evaluator: identical for every system."""
    res: dict[str, Any] = {
        "pred_decision": out.get("decision"),
        "pred_scam": bool(out.get("scam")),
        "pred_injection": bool(out.get("injection_detected")),
    }
    letter = out.get("cover_letter") or ""
    if out.get("decision") == "bid" and letter:
        pool = [
            e.model_dump()
            for e in await asyncio.to_thread(
                lambda: retriever.retrieve(row["job"], row["persona"], k=10)
            )
        ]
        known = {e["evidence_id"] for e in pool}
        for eid in out.get("evidence_ids") or re.findall(r"\[([0-9a-f]{8,32})\]", letter):
            if eid not in known:
                c = retriever.res.store.get(eid)
                if c:
                    pool.append(
                        {
                            "evidence_id": c.chunk_id,
                            "title": c.title,
                            "excerpt": c.text[:1200],
                            "type": c.doc_type,
                        }
                    )
        claims, _ = await verify_claims(letter, pool)
        res.update(
            {
                "claims": len(claims),
                "unsupported": sum(1 for c in claims if c.label == "unsupported"),
                "unsupported_rate": unsupported_rate(claims),
                "violations_in_output": len(
                    [v for v in check_text(letter) if v.severity == "block"]
                ),
                "words": len(letter.split()),
            }
        )
    return res


async def submit(row: dict[str, Any], out: dict[str, Any], adapter, system: str) -> str | None:  # type: ignore[no-untyped-def]
    if adapter is None or out.get("decision") != "bid" or not out.get("cover_letter"):
        return None
    job = row["job"]
    bid_type = (
        job.get("payment_type") if job.get("payment_type") in ("fixed", "hourly") else "fixed"
    )
    amount = float(out.get("bid_amount") or job.get("budget") or job.get("hourly_max") or 30)
    try:
        r = await adapter.submit_proposal(
            ProposalDraftIn(
                job_id=row["job_id"],
                cover_letter=out["cover_letter"][:5000].ljust(50),
                bid_amount=max(1.0, amount),
                bid_type=bid_type,
                idempotency_key=f"mac-{system}-{row['job_id']}",
            )
        )
        return r.status
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"[:80]


def row_log(args: argparse.Namespace) -> RowLog:
    return RowLog("multiagent", extra={"gigsim": args.gigsim}, fresh=getattr(args, "fresh", False))


async def main_async(args: argparse.Namespace) -> list[dict[str, Any]]:
    deps = make_deps()
    retriever = build_retriever("v2_hybrid")
    jobs = sample_jobs(max(1, args.jobs // 3), seed=args.seed)[: args.jobs]
    systems = args.systems.split(",")
    log, guard = row_log(args), QuotaGuard()
    base = settings.env().gigsim_base_url.rstrip("/")
    async with httpx.AsyncClient(
        timeout=15
    ) as c:  # the baselines read jobs through get_job, so open them in GigSim
        await c.post(f"{base}/admin/open", json=[r["job_id"] for r in jobs])
    adapters: dict[str, Any] = {}
    if args.gigsim:
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

        async with httpx.AsyncClient(timeout=15) as c:
            for system in systems:
                key = f"eval-mac-{system}-{args.seed}"
                await c.post(
                    f"{base}/admin/accounts",
                    params={"api_key": key, "freelancer_id": key, "connects": 10000},
                )
                adapters[system] = GigSimAdapter(base_url=base, token=key)
    for row in jobs:
        for system in systems:
            if guard.stopped or log.get(f"{system}:{row['job_id']}"):
                continue
            mark = guard.mark()
            t0 = time.perf_counter()
            extra: dict[str, Any] = {}
            try:
                if system == "single":
                    out, usage = await run_single(row, deps)
                elif system == "supervisor":
                    out, usage = await run_supervisor(row, deps)
                else:
                    out, usage, extra = await run_graph(row, deps)
                err = None
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                if guard.spoiled(mark, exc):
                    continue
                out, usage, err = {}, {}, f"{type(exc).__name__}: {exc}"[:300]
            latency = time.perf_counter() - t0
            ev = await evaluate(row, out, retriever) if not err else {}
            if guard.spoiled(mark):  # the claim judge in evaluate() also uses a model
                continue
            status = await submit(row, out, adapters.get(system), system) if not err else None
            rec = {
                "system": system,
                "job_id": row["job_id"],
                "persona": row["persona"],
                "label_source": row["label_source"],
                "gold_decision": row.get("gold_decision"),
                "gold_scam": bool(row.get("gold_scam")),
                "gold_injection": bool(row.get("gold_injection")),
                **ev,
                **extra,
                "gigsim_status": status,
                "tokens": sum(usage.values()),
                "cost_usd": cost(usage),
                "latency_s": round(latency, 2),
                "error": err,
            }
            log.add(f"{system}:{row['job_id']}", rec)
            print(
                f"  {system:10s} {row['job_id']} gold={row.get('gold_decision')!s:5s} pred={ev.get('pred_decision')!s:5s} unsup={ev.get('unsupported', '-')} tok={rec['tokens']} {latency:5.1f}s {err or ''}"
            )
    return log.collect([f"{s}:{r['job_id']}" for r in jobs for s in systems], guard)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for system in sorted({r["system"] for r in rows}):
        rs = [r for r in rows if r["system"] == system]
        ok = [r for r in rs if not r.get("error")]
        lab = [r for r in ok if r["gold_decision"] in ("bid", "skip")]
        props = [r for r in ok if r.get("claims") is not None]
        sent = [
            r
            for r in ok
            if r.get("gigsim_status") and not str(r["gigsim_status"]).startswith("error")
        ]
        scams = [r for r in ok if r["gold_scam"]]
        out[system] = {
            "n": len(rs),
            "errors": len(rs) - len(ok),
            "bid_skip_accuracy": round(
                sum(
                    1 for r in lab if (r["pred_decision"] == "bid") == (r["gold_decision"] == "bid")
                )
                / len(lab),
                3,
            )
            if lab
            else None,
            "scam_recall": round(
                sum(1 for r in scams if r["pred_scam"] or r["pred_decision"] == "skip")
                / len(scams),
                3,
            )
            if scams
            else None,
            "proposals": len(props),
            "unsupported_claims_per_proposal": round(
                sum(r["unsupported"] for r in props) / len(props), 3
            )
            if props
            else None,
            "unsupported_rate": round(sum(r["unsupported_rate"] for r in props) / len(props), 3)
            if props
            else None,
            "violations_in_output": sum(r.get("violations_in_output", 0) for r in props),
            "violations_caught_by_guard": sum(r.get("guard_caught", 0) for r in ok),
            "gigsim_reply_rate": round(
                sum(1 for r in sent if r["gigsim_status"] in ("replied", "interview", "hired"))
                / len(sent),
                3,
            )
            if sent
            else None,
            "tokens_per_job": round(sum(r["tokens"] for r in ok) / len(ok)) if ok else None,
            "latency_s": summary_stats([r["latency_s"] for r in ok]),
            "cost_usd_per_job": round(sum(r["cost_usd"] for r in ok) / len(ok), 6) if ok else None,
        }
        by_source: dict[str, Any] = {}
        for src in sorted({r["label_source"] for r in lab}):
            s_rows = [r for r in lab if r["label_source"] == src]
            by_source[src] = round(
                sum(
                    1
                    for r in s_rows
                    if (r["pred_decision"] == "bid") == (r["gold_decision"] == "bid")
                )
                / len(s_rows),
                3,
            )
        out[system]["accuracy_by_job_type"] = by_source
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=50)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--systems", default="single,supervisor,graph")
    ap.add_argument("--gigsim", action="store_true")
    ap.add_argument("--summary-only", action="store_true", help="summarise the saved rows")
    ap.add_argument("--fresh", action="store_true", help="discard saved rows and start over")
    args = ap.parse_args()
    rows = list(row_log(args).rows.values()) if args.summary_only else asyncio.run(main_async(args))
    summary = summarise(rows)
    path = write_result("multiagent_comparison", {"config": vars(args), "systems": summary})
    for s, m in summary.items():
        print(
            f"{s:10s} n={m['n']} acc={m['bid_skip_accuracy']} unsup/prop={m['unsupported_claims_per_proposal']} reply={m['gigsim_reply_rate']} tok/job={m['tokens_per_job']} p95={m['latency_s']['p95']}s"
        )
    print(f"-> {path}")


if __name__ == "__main__":
    main()
