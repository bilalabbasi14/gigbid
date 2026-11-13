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

## 3. R&D question A: tool granularity

**Hypothesis.** One tool per capability with a precise description beats a few coarse tools on
tool selection and arguments, and the price is tokens: every tool schema is sent with every call.

**Setup.** 40 single-call tasks covering all 18 capabilities of our three MCP servers
(`evals/datasets/tool_tasks.jsonl`), one model (gpt-oss-20b, no fallback), three tool sets built
from the committed schema snapshots: *fine* (the shipped tools and descriptions), *coarse*
(three tools, one per server, taking an operation name and arguments) and *best* (the fine tools
with descriptions rewritten as what it does, when to use it, when not to and what to use instead;
`evals/datasets/tool_descriptions_v2.yaml`). Source: `evals/results/tool_design.json`.

| Tool set | Tools | Right tool | Right arguments | Tokens per task |
|---|---|---|---|---|
| Coarse | 3 | 0.75 | 0.35 | 565 |
| Fine | 18 | 0.95 | 0.825 | 2,023 |
| Best | 18 | 0.975 | 0.875 | 2,391 |

**Findings.** Granularity matters most for arguments: with one generic `arguments` object the
model filled them correctly on barely a third of the tasks, against 83% with typed schemas.
Coarse tools also mixed up near neighbours (search vs list, threads vs messages). Rewriting the
descriptions added 3 points of selection and 5 of argument accuracy for 18% more tokens. Two of
the three fine-grained misses are one task: a request to see what a submission would send was
answered with `create_proposal_draft`, which returns the same preview without spending Connects;
the gold label wanted `submit_proposal` with `dry_run`. We count it as a miss but it is the safer
reading.

**What ships.** The fine-grained tools, now publishing the rewritten descriptions
(`mcp_servers/tool_descriptions.yaml`; the measured docstring surface is frozen in
`evals/datasets/tool_surface_docstrings/`). About 1,800 extra input tokens per call is the price
of correct arguments. Inside GigBid the graph nodes call tools by name, so they do not pay it; it
falls on model-driven callers such as the single-agent baseline and external MCP clients.

## 4. R&D question B: retrieval and claim verification (*partly pending*)

**Hypothesis.** Freelancer evidence is written three ways: case studies in prose, code and
READMEs, and short reviews. Exact skill names ("Airflow", "dbt") matter as much as meaning, so
hybrid retrieval should beat dense retrieval, and a cross-encoder should help most where job
posts and evidence use different words.

**Setup.** 193 dev jobs over three personas, gold relevant projects per job, retrieval at
project level, past proposals for the same job excluded (leakage guard). Embeddings
`bge-base-en-v1.5`, reranker `bge-reranker-base`, both on CPU (`evals/results/rag_summary.json`).

| Variant | Recall@5 | MRR | nDCG@10 | ai_ml | fullstack | data_analyst |
|---|---|---|---|---|---|---|
| V0 dense | 0.672 | 0.432 | 0.486 | 0.700 | 0.609 | 0.707 |
| V2 hybrid (BM25 + dense, RRF) | 0.693 | 0.441 | 0.505 | 0.731 | 0.586 | 0.760 |
| V3 cross-encoder rerank | 0.654 | 0.420 | 0.479 | 0.754 | 0.500 | 0.707 |
| V4 outcome-aware | 0.654 | 0.439 | 0.503 | 0.715 | 0.523 | 0.723 |
| V5 multi-vector projects | 0.587 | 0.396 | 0.494 | 0.654 | 0.531 | 0.576 |
| V8 corrective loop | 0.638 | 0.419 | 0.472 | 0.739 | 0.469 | 0.707 |

Persona columns are Recall@5. Source: `evals/results/rag_summary.json`.

**Findings so far.** Hybrid retrieval helps overall, most for the data analyst (+0.053 Recall@5
over V0), and costs fullstack 0.023. The reranker is a negative result: it is the best variant
for ai_ml and the second worst for fullstack, so it does not ship as a global stage. The
corrective loop shows the same split, which fits the fact that it grades with the same
cross-encoder. Why the cross-encoder demotes fullstack evidence is not yet established; a
per-query comparison of V2 and V3 on the fullstack jobs is pending. The LLM-based
variants (V1 decomposition, V7 HyDE, `best`), V6 contextual and V9 skill graph were not run:
on the free tier their per-query model calls did not fit next to the proposal runs.

**Claim verification.** Six proposals with V2 retrieval, drafted, verified and sent to GigSim
(`evals/results/proposal_eval_v2_hybrid.json`): 0.67 unsupported claims per proposal before
verification (9.5% of claims), none after; the Critic passed 5 of 6 after 1.2 revisions on
average; no compliance blocks. The verifier removed or rewrote every unsupported sentence
before the Critic saw the draft, which is the property the architecture depends on. With LLM
clients, 1 of 6 proposals got a reply (and a hire). Six proposals per variant cannot show a
reply-rate difference between variants; the V0 comparison is pending (*`proposal_eval_v0_naive.json`*).

**Judge calibration** (*pending the human labels*). The judge scored the 30 calibration items
(`evals/results/judge_scores.json`), past proposals drawn evenly from won, replied and ignored.

**What ships.** V2 hybrid retrieval (`agent/config.yaml` rag.variant): the best Recall@5
overall, no model call and no cross-encoder, so it adds no quota and no latency. Reranking is
kept as an option, not a default, because its gain on one persona is paid for by another.

## 5. R&D question C: single agent, supervisor, graph (*results pending: `multiagent_comparison.json`*)

**Setup.** The same dev jobs go through three systems with the same models and the same tools:
(a) one ReAct agent holding every tool, prompted to analyse, decide, price and draft
(`agent/prompts/baseline_single_agent.md`); (b) a prebuilt `langgraph-supervisor` with analyst,
risk, writer and critic workers (`baseline_supervisor.md`); (c) GigBid's hand-built graph. Each
draft is scored by the same claim verifier and Compliance Guard, and bids go to GigSim for the
simulated client's reaction (`evals/runners/multiagent_compare.py`). The brief asks for 50 jobs;
the free tier allowed a much smaller sample, stated with the results, so this section reports
direction, not significance.

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

## 7. Signature extension: Portfolio builder (*results pending: `x3_eval.json`*)

The builder reads a freelancer's repositories through the GitHub MCP server, extracts facts
(languages, dependencies, tests, CI, commit history), drafts one case study per repository in
which every claim cites a fact, verifies and repairs the claims, and saves only what the user
approves (`docs/EXTENSION.md`).

**How it is measured.** For each persona with repositories, three indexes: *original* (every
project written up by hand), *base* (the case studies of repository projects removed, a freelancer
who has code but never wrote it up) and *built* (base plus the builder's case studies). Retrieval
is scored on the dev jobs whose gold evidence includes a repository project. Each case study is
also scored for claims, unsupported rate before and after repair, facts cited, and library recall
and precision against the project's own metadata.

**A finding before the result.** The first run looked complete but 7 of 25 case studies had no
verified claims: the medium model's output-per-minute limit was rejecting every verifier call and
the nodes fell back to heuristics without failing (commit `78f47bd`, ADR 0003). That run was
discarded; evaluations now discard any item that saw a failed model call.

## 8. Failure analysis (*results pending: `failure_taxonomy.json`*)

Every failed dev job from the decision, proposal and injection runs is classified by the earliest
stage that went wrong: tool error, injection, missed scam, missed evidence, wrong skip, wrong bid,
mispriced, unsupported claim, generic opening, compliance miss or block
(`evals/runners/failure_analysis.py`). The fix tried for each group and whether it worked is
recorded below.

Fixes already made from failures found during development (each with its commit):

| Failure | Group | Fix | Worked? |
|---|---|---|---|
| Claim verifier crashed on drafts with partly supported claims (invalid action label) | tool error | label set fixed, regression test (`52db615`) | yes |
| Verification silently skipped under per-minute output limits | tool error | per-prompt output budgets, oversize retry, failed-call accounting (`78f47bd`, `a2acca7`) | yes (no failed calls in the re-profile) |
| Pricing ignored the platform's minimum hourly rate | mispriced | pricing reads the policy pack's minimums (`452747b`) | yes (unit test) |
| Inbox showed "awaiting approval" before the job record existed | tool error | status written only after the record sync (`a51da09`) | yes |

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

**Budgets before the hidden run** (`evals/results/budget_check.json`; cost at Groq list prices,
the free plan itself costs nothing). Cost is within budget: about $0.008 per analysed job and
$0.033 per proposal at p95, against $0.01 and $0.05. Latency is not: p95 82 s per job against 60
and 365 s per proposal against 120, measured on the development laptop with the free tier's rate
limits. Most of the proposal time is Critic send-backs (zero to two per proposal), so the
optimisation that matters is a draft that passes the Critic the first time, not a faster model.
The hidden-run numbers will be reported against the same budgets without adjustment.

**Choosing the model configuration** (`evals/results/profile_comparison.json`). The open
profile (Groq: gpt-oss-20b, Qwen3.8 27B, gpt-oss-120b) and the local profile (qwen3:4b-instruct
on the laptop CPU, i5-1155G7 with 7.8 GB and no GPU) decided the same nine dev jobs. The local
profile scored bid-or-skip F1 0.75 against 0.57 and the two agreed on 44% of decisions, which
nine jobs cannot separate from noise. Speed and hosting decided: the local profile needs p50 296 s
and p95 666 s per job at 2.8 output tokens per second of wall time, against p50 92 s for the open
profile and a 60 s budget, and the 4 GiB deployment VM has no room for a local model. The open
profile ships; the local profile runs the CI smoke evaluation, where it costs no API quota.
