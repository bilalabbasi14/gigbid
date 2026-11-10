# Getting Started

## 1. Understand the product
GigBid assists a freelancer with job discovery, risk assessment, portfolio matching, pricing,
proposal drafting and client conversations. The freelancer remains in control of every external
action.

## 2. Suggested implementation order
1. Inspect the provided GigSim API and its documentation.
2. Implement one marketplace port with a GigSim adapter.
3. Build a read-only Portfolio MCP server.
4. Define typed Pydantic hand-offs for job, risk, fit, pricing and proposal data.
5. Implement a basic end-to-end path for one job.
6. Add portfolio ingestion and a baseline dense retriever (V0).
7. Add claim verification before the Critic.
8. Add the parallel LangGraph branches and bounded critique loop.
9. Add an interrupt-based approval flow and persistence.
10. Build the UI and stream progress.
11. Add evaluation, tracing, tests, deployment and your chosen extension.

## 3. Suggested folder responsibilities
- `apps/api`: FastAPI endpoints and streaming bridge.
- `apps/web`: React/Next.js TypeScript user interface.
- `agent`: graph state, nodes, prompts, model config and memory rules.
- `rag`: portfolio ingestion, retrievers, variants and claim verification.
- `mcp_servers`: tool servers for portfolio, marketplace and workspace.
- `worker`: scheduled scouting and long-running jobs.
- `data/sample`: tiny illustrative data only.
- `evals`: your own development evaluation scripts and results.
- `tests`: unit, integration, contract and end-to-end tests.
- `docs`: architecture, tools, runbook, data card and AI usage notes.

## 4. First end-to-end experiment
Use one synthetic job from `data/sample/jobs.json` and one profile from
`data/sample/freelancers.json`. Retrieve relevant evidence from `portfolio_items.json`.
Return a structured recommendation and a proposal draft that cites evidence IDs.
Do not implement automatic sending.

## 5. Questions to answer in your R&D report
- Which tool design gave the most accurate tool selection and arguments?
- Which RAG variant improved evidence retrieval on your development set?
- Did better retrieval improve simulated client replies? Why or why not?
- When did a single agent perform better than a multi-agent graph?
- What failed, how did you diagnose it, and what changed after the fix?
- How did you test prompt-injection resistance and human approval?

## 6. Before committing
- Confirm `.env` and credentials are not tracked.
- Confirm the supplied `gigsim/` directory has not been modified.
- Confirm every proposal claim has traceable evidence.
- Confirm external actions require explicit human approval.
- Record actual measurements; never invent evaluation numbers.
