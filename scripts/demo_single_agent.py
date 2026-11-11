"""Part A deliverable: a single agent drafting one grounded proposal for a GigSim job, using only
MCP tools (marketplace reads + portfolio evidence). Nothing is submitted.

  uv run python -m scripts.demo_single_agent [--job-id JOB] [--persona ai_ml] [--query "rag chatbot"]
Requires: Postgres with the persona ingested (make ingest), GigSim running (make gigsim), GROQ key.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage

from agent import llm
from agent.mcp_client import ToolProvider, in_process_loader
from agent.prompts import load_prompt


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id")
    ap.add_argument("--persona", default="ai_ml")
    ap.add_argument("--query", default=None)
    args = ap.parse_args()

    provider = ToolProvider(loader=in_process_loader)
    tools = {t.name: t for t in await provider.tools_for("single_agent")}
    print(f"tools available to the single agent: {sorted(tools)}")

    if args.job_id:
        job = await tools["get_job"].ainvoke({"job_id": args.job_id})
    else:
        found = await tools["search_jobs"].ainvoke(
            {"query": args.query or "machine learning", "limit": 5}
        )
        job = found["items"][0]
        job = await tools["get_job"].ainvoke({"job_id": job["job_id"]})
    print(f"\nJOB: {job['title']}  [{job['payment_type']}, connects {job['connects_cost']}]\n")

    # Requirement extraction, then one evidence search per requirement (the grounded part).
    sys_prompt, user_prompt = load_prompt("single_agent_requirements")
    resp = llm.invoke_for_node(
        "analyst",
        [
            SystemMessage(content=sys_prompt),
            HumanMessage(
                content=user_prompt.format(
                    job_title=job["title"], job_description=job["description"]
                )
            ),
        ],
    )
    reqs = [r.strip("-• ").strip() for r in str(resp.content).splitlines() if r.strip()][:5]
    print("requirements:", *[f"  - {r}" for r in reqs], sep="\n")

    evidence = []
    for r in reqs:
        res = await tools["search_evidence"].ainvoke(
            {"requirement": r, "k": 3, "persona": args.persona}
        )
        for item in res["items"][:2]:
            evidence.append({"requirement": r, **item})
    seen, unique = set(), []
    for e in evidence:
        if e["evidence_id"] not in seen:
            seen.add(e["evidence_id"])
            unique.append(e)
    print(f"\nevidence items: {len(unique)}")
    for e in unique:
        print(
            f"  [{e['evidence_id']}] {e['type']:11s} {e['title'][:60]}  <- {e['requirement'][:40]}"
        )

    sys_prompt, user_prompt = load_prompt("single_agent_writer")
    ev_text = "\n\n".join(
        f"[{e['evidence_id']}] ({e['type']}, {e['date']}) {e['title']}\n{e['excerpt'][:600]}"
        for e in unique
    )
    resp = llm.invoke_for_node(
        "writer",
        [
            SystemMessage(content=sys_prompt),
            HumanMessage(
                content=user_prompt.format(
                    job_title=job["title"],
                    job_description=job["description"],
                    evidence=ev_text,
                    questions="\n".join(job.get("screening_questions") or ["(none)"]),
                )
            ),
        ],
    )
    print("\n=== DRAFT (not submitted) ===\n")
    print(resp.content)

    preview = await tools["create_proposal_draft"].ainvoke(
        {
            "draft": {
                "job_id": job["job_id"],
                "cover_letter": str(resp.content)[:4000],
                "bid_amount": float(job.get("budget") or job.get("hourly_max") or 30),
                "bid_type": job["payment_type"],
                "idempotency_key": f"demo-{job['job_id']}",
                "dry_run": True,
            }
        }
    )
    print("\n=== DRY-RUN PREVIEW (what submit would send) ===")
    print(json.dumps(preview.get("preview") or preview, indent=2)[:800])


if __name__ == "__main__":
    asyncio.run(main())
