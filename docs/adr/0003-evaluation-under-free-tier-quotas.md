# ADR 0003: Evaluation under free-tier model quotas

**Status:** accepted · **Date:** 2026-11-11

## Context
The `open` profile runs on Groq's free plan. Each chat model (`gpt-oss-20b`, `gpt-oss-120b`,
`qwen3.8-27b`) is capped at 200k tokens per day and 8k tokens per minute. One analysed job uses
several thousand tokens and one drafted proposal far more, so the full evaluation (decisions,
proposals for three retrieval variants, injection, X3, the multi-agent comparison and the judge)
needs several million tokens: several days of quota. Three failure modes showed up:

- A daily cap was retried like a per-minute limit for minutes and then reported as a generic
  error, losing the run.
- Groq lowers output-token limits under load: requests for the medium model were rejected as
  "too large" for a 1,000 output-tokens-per-minute limit while our default `max_tokens` was
  1,200, and per-minute 429s were retried for about 30 s against a 60 s window. Each failure
  sent a node to its heuristic fallback without anyone noticing; the first X3 run had 7 of 25
  case studies never verified.
- Nodes degrade on model failure (heuristic risk score, retrieval-only fit, sentence-split claims).
  That is right in production, but an evaluation would silently record degraded rows as if they
  came from the configured models. A fallback model would likewise mix models inside one result.

Gemma 4 through the Gemini API (open weights, separate quota) was tried as extra capacity and
returned mostly 500/503 errors at about 20 s per call, so it is not used.

## Decision
- `agent/llm.py` recognises a daily cap, skips that model until the provider's reset time and
  goes to the fallback. When every allowed model is capped it raises `QuotaExhaustedError` and
  counts it.
- An oversize request is retried at once with a `max_tokens` below the stated limit, and a
  per-minute limit waits as long as the provider says. Send fan-out is capped
  (`budgets.max_parallel_branches`).
- Evaluations set `GIGBID_STRICT_MODELS=1`: no fallback models, so each node is measured on its
  configured model. Any model call that still fails after its retries discards the item in
  flight, which is redone on the next run.
- Every LLM-heavy runner appends finished items to `evals/results/<name>_rows.jsonl` and skips
  them on the next run. A row carries a fingerprint of the prompts, policy pack and
  behaviour-relevant config, and rows from another configuration are dropped, never mixed in.
- When a daily cap is hit, the item in flight is discarded, the runner exits with status 3 and
  the queue (`scripts/run_evals.sh`) reports `PARTIAL`. Rerunning the queue later continues.
- A result file (`evals/results/<name>.json`) is written only when every planned item is done, so
  the README never shows partial numbers.

## Consequences
- Results take several days of wall-clock time on the free plan; Groq's paid plan would finish
  them in a day for a few dollars.
- Sample sizes are chosen to fit the quota and are stated next to every metric.
- Changing a prompt or a threshold invalidates the affected rows, which costs quota but keeps
  every number traceable to one configuration.
