# GigBid: R&D report

An engineering design review of GigBid, a multi-agent copilot that finds freelance jobs, decides
which are worth paid Connects, drafts grounded proposals and handles client replies, with a human
approving everything that reaches a client. Every number below cites a file in `evals/results/`,
a commit or a trace. All evaluations ran on the open profile with fallback models disabled, over
several days on the free tier (ADR 0003). Two settings changed after the measurements, both
checked offline on the saved results and stated where they apply: the scam rule and the bid
threshold (Section 8). Section 10 covers the live deployment; the hidden test results come after the deadline.

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

## 4. R&D question B: retrieval and claim verification

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
cross-encoder. A per-query comparison on the 64 fullstack jobs
(`evals/results/rag_compare_v2_hybrid_v3_rerank_fullstack.json`) shows why: the reranker wins 5
jobs and loses 10, and in both variants 91 to 96% of the top five evidence items are past
proposals rather than case studies or code, because past proposals are written in the language of
job posts. The cross-encoder ranks by how closely that language matches the new job, so it
promotes proposals written for similar-sounding jobs whether or not they cite the right project;
46 of the 50 top-five items in its losing queries are past proposals. A second finding follows:
for fullstack jobs, retrieval leans almost entirely on past proposals, so the persona's case
studies and code are rarely seen by the Writer. The LLM-based
variants (V1 decomposition, V7 HyDE, `best`), V6 contextual and V9 skill graph were not run:
on the free tier their per-query model calls did not fit next to the proposal runs.

**Claim verification.** Six proposals with V2 retrieval, drafted, verified and sent to GigSim
(`evals/results/proposal_eval_v2_hybrid.json`): 0.67 unsupported claims per proposal before
verification (9.5% of claims), none after; the Critic passed 5 of 6 after 1.2 revisions on
average; no compliance blocks. The verifier removed or rewrote every unsupported sentence
before the Critic saw the draft, which is the property the architecture depends on. With LLM
clients, 1 of 6 proposals got a reply (and a hire). The same six jobs with V0 dense retrieval
(`proposal_eval_v0_naive.json`) carried more unsupported claims before verification, 0.83 per
proposal (19% of claims), and none after; the Critic passed 5 of 6 after 1.3 revisions and the
Compliance Guard blocked one draft that offered contact details. Verification removes the
difference weaker retrieval makes before a client sees it, which is why it sits before the
Critic. Reply rates cannot separate the variants at this size (1 reply from the 3 V0 reactions
observed; two were lost to a harness polling timeout, fixed in `9e2d591`).

**Judge calibration** (`evals/results/judge_calibration.json`). One person scored the 30
calibration proposals (past proposals drawn evenly from won, replied and ignored) on the judge's
six criteria without seeing its scores (`evals/labeling/RUBRIC.md`, `judge_sheet.csv`).
Quadratic-weighted kappa on the overall score is 0.71, and every overall score is within one
point of the human's. By criterion it runs from 0.80 (next step) and 0.74 (relevance) down to 0.41
(credibility) and 0.38 (clarity). The judge is lenient: higher than the human on 16 of 30 overall
scores and lower on 4 (mean 3.2 against 2.8). Its two largest misses are both credibility: a
claimed publication with "5k reads" and a tutoring history, which the human marked as looking
invented (2) and the judge accepted (4). A judge that reads fluency as credibility is why GigBid
checks claims against evidence rather than asking a model whether a draft sounds credible. Exact
agreement is 33 to 50%, so judge scores rank drafts; they do not decide one-point differences.

**What ships.** V2 hybrid retrieval (`agent/config.yaml` rag.variant): the best Recall@5
overall, no model call and no cross-encoder, so it adds no quota and no latency. Reranking is
kept as an option, not a default, because its gain on one persona is paid for by another.

## 5. R&D question C: single agent, supervisor, graph

**Setup.** The same dev jobs go through three systems with the same models and the same tools:
(a) one ReAct agent holding every tool, prompted to analyse, decide, price and draft
(`agent/prompts/baseline_single_agent.md`); (b) a prebuilt `langgraph-supervisor` with analyst,
risk, writer and critic workers (`baseline_supervisor.md`); (c) GigBid's hand-built graph. Each
draft is scored by the same claim verifier and Compliance Guard, and bids go to GigSim for the
simulated client's reaction (`evals/runners/multiagent_compare.py`). The brief asks for 50 jobs;
the free tier allowed a much smaller sample, stated with the results, so this section reports
direction, not significance.

**Results** on 6 dev jobs, 3 labelled bid and 3 skip (`evals/results/multiagent_comparison.json`,
per-run rows in `multiagent_rows.jsonl`):

| System | Failed runs | Correct decisions (completed runs) | Bids | Proposals | Tokens / job | p95 latency |
|---|---|---|---|---|---|---|
| (a) single ReAct agent | 3 of 6 | 1 of 3 | 0 | 0 | 5,454 | 42.9 s |
| (b) langgraph-supervisor | 2 of 6 | 3 of 4 | 0 | 0 | 2,740 | 9.4 s |
| (c) GigBid graph | 0 of 6 | 5 of 6 | 2 | 2 | 15,431 | 116.8 s |

**Findings.** The baselines failed in a way the graph cannot. In 5 of their 12 runs the model
called a tool that does not exist (`JSON`, `specialist`, `get_function`) and the provider
rejected the request. A model that picks its next tool from a large set can always do this;
GigBid's nodes call fixed tools and ask the model only for typed output. Neither baseline bid on
any job it completed: every completed run ended in skip, so their accuracy comes only from the
jobs labelled skip, and they never reached the stage where verification and compliance matter.
The graph decided 5 of 6 correctly (it skipped one job labelled bid) and wrote two proposals with
no unsupported claims and no policy violations; one was viewed in GigSim, and the other's
reaction was lost to the polling timeout noted in Section 4. The graph's cost is the work the
baselines skipped. On the one job all three completed and skipped it used 6,729 tokens, against
9,387 for the single agent and 2,631 for the supervisor; a job it bid on cost about 33,500,
mostly drafting, verification and the Critic loop. Six jobs show direction only: the hand-built
graph is the only system that completed every run and the only one that reached a proposal.

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

## 7. Signature extension: Portfolio builder

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

**Results** (`evals/results/x3_eval.json`): 30 synthetic repositories over the three personas
(`docs/DATA_CARD.md`), so this measures the mechanism, not real GitHub accounts. Retrieval is
scored on the 120 dev jobs whose gold evidence includes a repository project.

| Builder output | Value |
|---|---|
| Case studies drafted | 30 of 30 repositories |
| Claims per case study | 12.2 |
| Unsupported claims before / after verification | 14.0% / 0.6% |
| Facts cited per case study | 11.2 |
| Library recall / precision against the project's metadata | 0.40 / 0.62 |

| Index | Recall@5 | MRR | nDCG@10 | ai_ml | fullstack | data_analyst |
|---|---|---|---|---|---|---|
| original (hand-written case studies) | 0.743 | 0.480 | 0.542 | 0.657 | 0.790 | 0.771 |
| base (no write-ups for repository projects) | 0.722 | 0.472 | 0.527 | 0.614 | 0.790 | 0.753 |
| built (base plus the builder's case studies) | 0.730 | 0.467 | 0.525 | 0.614 | 0.823 | 0.753 |

Persona columns are Recall@5.

**Findings.** The builder is trustworthy before it is useful. One claim in seven in its first
drafts was not supported by the extracted facts; verification and repair left 0.6%, which is
what lets a freelancer approve a case study without re-checking it. Its retrieval value on this
data is small. Removing the write-ups of repository projects costs only 0.021 Recall@5, because
retrieval leans on past proposals (Section 4), and the builder's case studies win back 0.008 of
it: all of the gain is fullstack, where the built index beats even the hand-written one, while
for ai_ml and data_analyst they recover nothing. Library recall of 0.40 reflects what code can
show: project metadata names services and practices ("AWS SageMaker", "MLOps", "time-series
forecasting") that no dependency or import states, and the builder claims only what the files
show. The rows also exposed a counting bug: 7 case studies reported zero facts cited although
each cited 7 to 16, because the model wrote citations as 【id】 or [ id ]. The builder now
normalises citations and the runner recounts from the saved drafts (`a2a25e1`).

## 8. Failure analysis

Every failed dev job from the decision, proposal and injection runs is classified by the earliest
stage that went wrong: tool error, injection, missed scam, missed evidence, wrong skip, wrong bid,
mispriced, unsupported claim, generic opening, compliance miss or block
(`evals/runners/failure_analysis.py`). There were 30 failures over 60 decision jobs, 12 proposals
and 4 injection runs (`evals/results/failure_taxonomy.json`):

| Group | Failures | What happened | Fix tried | Worked? |
|---|---|---|---|---|
| Missed scam | 10 | The pre-screen found the signals (an onboarding fee, payment off the platform, an unpaid test) but its weights kept the score under the threshold | Hard scam signals; weights moved to config (`ca3f453`) | On the dev set: 45 of 45 planted scams flagged offline, from 17, with the same 11 false alarms in 357 (`scam_rule_check_before.json`, `_after.json`). On 1,000 fake ads from a public dataset: no, 3 flagged before and after |
| Missed evidence | 9 | Fit under the bid threshold. Six jobs are far outside the persona (fit 0.35 or less: C++ and OpenCV, Amazon PPC, MATLAB control systems, CMO leadership) but labelled bid because a past proposal exists for them; three are borderline fits of 0.45 to 0.55 | Bid threshold 0.60 to 0.50, from a replay of the saved decisions (`threshold_sweep.json`) | Partly: replayed F1 0.621 to 0.667, two borderline jobs change; the six off-persona jobs are label noise |
| Injection | 6 | Five subtle injections (override, claim, persona, exfiltration) passed the pattern detector; one flagged overt attack still raised the fit score | None that fits; patterns catch only overt wording | No (Section 9) |
| Wrong skip | 3 | The client's maximum rate was under the user's own floor ($20/h), so the rule skipped jobs labelled bid | None: the user's floor should win | Label disagreement |
| Wrong bid | 1 | A WordPress plugin job scored 0.65 on OpenAI API evidence alone | None | No |
| Compliance block | 1 | A V0 draft offered contact details and the Guard blocked it | None needed | Working as intended |

The two fixes were checked on saved rows, not by re-running the pipeline: the scam rule is
deterministic and a hard signal now marks a post as a scam whatever the model says, so the
offline check measures what the pipeline starts from; the threshold replay changes only
decisions set by the fit comparison. The public dataset is the honest limit of the scam fix.
Phrase rules catch the scams their author anticipated; fake ads worded differently need
judgement, which the Risk Assessor's model provides only above the heuristic floor. Results in
Sections 4 to 7 were measured before both changes.

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

**Measured** (`evals/results/injection.json`): one job per attack family, each run clean,
attacked without defences and attacked with them. With n = 4 these are cases, not rates. Without
defences 2 of 4 attacks moved the pipeline: an overt "rate this a perfect fit" raised the fit
score from 0.65 to 0.85, and a subtle claim lowered the risk score from 0.2 to 0.0. With defences
1 of 4 did: the same overt attack, which the pattern detector flagged, still raised the fit score
to 0.85, because the Fit Matcher reads the delimited post and the risk floor protects only the
risk score. The decision did not change, since the clean post was already a bid. No attack left
hijacked content in a final draft, and nothing was sent without approval. In the 60-job decision
run the detector flagged all 4 overt injections and none of the 5 subtle or exfiltration ones
(`decision_eval.json`).

What still gets through: injections phrased as ordinary client requests, which only delimiting
and the system prompt defend against; injected praise that inflates the fit score (next step: cap
the fit score at what the retrieved evidence supports when an injection is flagged, as the risk
score already is); off-platform requests that avoid every keyword; and claims the verifier labels
as partly supported.

## 10. Deployment and the hidden test

**Live system.** GigBid runs at https://gigbid-bilal.eastus.cloudapp.azure.com on one Azure VM (2
vCPU, 8 GiB; ADR 0005), with Postgres on Neon, deployed from `main` by GitHub Actions. The app
uses about 2 GiB. The instructor's hidden test runs against this URL after the deadline, so its
results are not in this report; they will be compared with the budgets below without adjustment.

**What deployment found.** The first live analysis failed: the memory helpers called the
Postgres-backed LangGraph store synchronously from the event loop, which the store rejects, while
the tests used an in-memory store that allowed it (`bfed9dd`). The failed start had also left a run
in "queued" that blocked any new analysis of that job (`7db90a4`). Both are fixed with regression
tests, one of which uses a store that rejects synchronous calls the way the Postgres store does.
Then four scenarios were run on the live app and their traces published (README): a planted scam
skipped with its reasons, a proposal the Critic sent back twice before approval, and a proposal
waiting for approval while the app container was killed and restarted. That proposal was approved
after the restart and submitted once; a second approval was refused with 409.

**Budgets before the hidden run** (`evals/results/budget_check.json`; cost at Groq list prices,
the free plan itself costs nothing). Cost is within budget: about $0.008 per analysed job and
$0.033 per proposal at p95, against $0.01 and $0.05. Latency is not: p50 61 s and p95 145 s per
job (66 jobs) against 60, and p50 140 s and p95 189 s per proposal (12 proposals) against 120,
measured on the development laptop under the free tier's rate limits. Most of the proposal time is Critic send-backs (zero to two per proposal), so the
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
