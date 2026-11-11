# GigBid: R&D report (draft)

An engineering design review of GigBid, a multi-agent copilot that finds freelance jobs, decides
which are worth paid Connects, drafts grounded proposals and handles client replies, with a human
approving everything that reaches a client. Every number below cites a file in `evals/results/`,
a commit or a trace. Sections marked *pending* fill in as the evaluation queue completes
(ADR 0003 explains why it runs over several days).

## 1. Problem and constraints

A freelancer on a marketplace spends paid Connects on every proposal. The work is: scan new jobs,
discard the scams and the poor fits, price the rest, write a proposal that proves fit with real
evidence, and keep conversations moving. GigBid automates the reading, judging and drafting. It
never automates the commitments:

| Never automated | Enforced by |
|---|---|
| Submitting a proposal, sending a message, spending Connects | an `interrupt()` before every submit and send node; `autonomy.auto_send: false` is not settable from the UI |
| Moving contact or payment off the platform | Compliance Guard rules on every draft and reply (Section 9) |
| Claiming experience the portfolio does not show | claim verification before the Critic; `no_fabrication` blocks what remains |
| Scraping or browser automation | all marketplace access goes through the official Upwork MCP server or the simulator, behind one port |

Declared budgets (`agent/config.yaml`):

| Budget | Value |
|---|---|
| p95 latency per job analysed | 60 s |
| p95 latency per proposal | 120 s |
| Cost per job analysed | $0.01 |
| Cost per proposal | $0.05 |
| Tokens per thread | 40,000 |
| Graph steps per thread | 40 |
| Critic send-backs | 2 |

Engineering constraints: a laptop with 7.8 GB of RAM and no GPU (embeddings and reranking run on
CPU), and the open-model free tier, which caps each model at 200k tokens a day (ADR 0003,
ADR 0004).

## 2. Architecture

Two LangGraph graphs share one runtime with a Postgres checkpointer and store
(`docs/ARCHITECTURE.md`).

- **Bid graph**, one thread per job: the Job Analyst, Risk Assessor and Fit Matcher run in
  parallel as `Send` branches, each writing its own state key. A rule-based Decision node and a
  deterministic Pricing Strategist follow. The Writer drafts from retrieved evidence only. The
  Verifier labels and repairs claims, the Critic sends back at most twice, and the Compliance Guard
  can block. Approval is an interrupt; submission is idempotent per thread, job and revision.
- **Conversation graph**, one thread per client conversation: intent classification, a reply
  with free interview slots from the Workspace server, compliance, approval, send.

Each agent exists because it has a different input, tool set or failure mode (table in
`docs/ARCHITECTURE.md`). The Risk Assessor reads client history, which the Analyst must not see.
The Decision and Pricing nodes are deterministic so that "why did it skip?" has an exact answer.

Agents never call the marketplace directly. They call allow-listed MCP tools
(`agent/mcp_client.py`) on three servers of our own (Portfolio, Marketplace, Workspace) and two
third-party ones (GitHub, Upwork). The Marketplace server sits on one `MarketplacePort` with a
GigSim adapter and an Upwork adapter. Write tools take an idempotency key, support `dry_run`, are
rate-limited per user and are logged to an append-only audit table (`docs/TOOLS.md`).

Stores: pgvector chunks and BM25 indexes for evidence; app tables for users, runs and the
pipeline; the LangGraph checkpointer for state; the LangGraph store for promoted memory only.

## 3. R&D question A: tool granularity (*pending: `evals/results/tool_design.json`*)

Hypothesis: fine-grained tools with precise descriptions raise selection and argument accuracy
over a few coarse tools, at a token cost per task. Setup: 40 tasks (`evals/datasets/tool_tasks.jsonl`),
three tool sets (fine, coarse, best), one model, exactly one call per task. Interim rows are in
`evals/results/tool_design_rows.jsonl`.

## 4. R&D question B: retrieval and claim verification (*pending*)

Variants V0 to V9 plus a composable `best`, retrieval metrics per persona
(`evals/results/rag_*.json`), claim verification before and after
(`evals/results/proposal_eval_*.json`), and the judge calibration (`judge_calibration.json`).

## 5. R&D question C: single agent, supervisor, graph (*pending: `multiagent_comparison.json`*)

## 6. The change request

The instructor's policy update has not been released, so the process was rehearsed with a
simulated policy v2 (`evals/results/change_request_rehearsal.json`, branch
`cr/simulated-policy-v2`). It added an AI-assistance disclosure, a 400-word limit, a ban on
asking for five-star reviews and a $10 minimum hourly rate.

**What made it cheap.** Rules are data. A rule in `data/policy_pack/policy.yaml` has an id, a
severity, a description, the kinds of text it applies to, and detectors composed from eight types
in `agent/policy.py`. The Compliance Guard checks every rule. The Writer and the Client Liaison
receive every rule's description in their prompts, so they comply by design. Pricing reads the
pack's minimum rates, and Connects costs arrive with each job from the marketplace. The
marketplace also reports its policy version, and the web app shows a warning while it differs
from the pack.

**What happened.** The first attempt changed only the pack and the version number, with no code,
and broke 10 unit tests. Those tests checked graph mechanics against the shipped rules, and their
fake drafts lacked the new disclosure. Commit `b872f4e` moved mechanics tests onto a frozen test
pack. The second attempt was the same three files (+22, -3 lines), with no code or prompt change,
and the suites passed 45 seconds after the edit was applied.

**What it says about the design.** A policy change costs a YAML edit when it can be expressed
with the existing detector types. A new kind of check costs one function in `agent/policy.py`.
The real update will be measured the same way when it arrives.

## 7. Signature extension: Portfolio builder (*pending: `x3_eval.json`*)

The builder reads a freelancer's repositories through the GitHub MCP server, extracts facts
(languages, dependencies, tests, CI, commit history), drafts one case study per repository in
which every claim cites a fact, verifies and repairs the claims, and saves only what the user
approves (`docs/EXTENSION.md`).

## 8. Failure analysis (*pending: rows from the decision and proposal runs*)

## 9. Safety and platform respect

| Threat | Defence | Where |
|---|---|---|
| Acting without consent | Interrupt before every submit and send; approvals survive restarts (Postgres checkpointer); submit is idempotent | `agent/graphs/bid_graph.py`, `scripts/durability_drill.py` |
| Off-platform contact or payment | Contact, link and keyword detectors block drafts and replies; the Liaison keeps conversations on the platform | `agent/policy.py`, `data/policy_pack/policy.yaml` |
| Invented experience | Every claim must cite retrieved evidence; unsupported claims are rewritten or removed before the Critic | `rag/verify.py` |
| Prompt injection in job posts and messages | Untrusted text is delimited and neutralised, the system prompt says it is data, pattern detection flags it, and the model cannot lower the heuristic risk score by more than 10% | `agent/guardrails.py`, `agent/nodes/risk_assessor.py` |
| Scraping, abuse of the platform | Official MCP servers only; per-user token buckets; conservative live polling interval | `mcp_servers/common/ratelimit.py`, `docs/RUNBOOK.md` |
| Leaked secrets or personal data | Secrets only in the environment; OAuth tokens encrypted at rest; PII masked in logs and the audit table | `apps/api/auth/token_store.py`, `agent/pii.py`, `mcp_servers/common/audit.py` |

What still gets through (*pending: `injection.json`*): injections phrased as ordinary client
requests, off-platform requests that avoid every keyword, and claims the verifier labels as
partly supported.

## 10. Hidden test results (*pending: after the deadline run*)
