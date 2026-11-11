# ADR 0004: Chat, embedding and reranker models

**Status:** accepted · **Date:** 2026-11-11 · **Supersedes:** the "Embeddings / reranker" row of
ADR 0001

## Context
Every model in the `open` profile must be open-weight, and embeddings and reranking must be open
models in every profile. The development laptop has 7.8 GB of RAM and no CUDA GPU, so local
models are limited to small quantised ones and CPU inference. In November 2026 Groq's free plan
offers three open chat models (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`),
each with its own daily quota.

## Decision
| Role | Model | Why |
|---|---|---|
| Small tier (scout, risk, pricing, compliance, intent, context lines) | `groq:openai/gpt-oss-20b` | The smallest and cheapest of the three; run at low reasoning effort |
| Medium tier (analyst, fit matcher, claim judge) | `groq:qwen/qwen3.8-27b` | Mid-sized; a separate quota from the gpt-oss models |
| Large tier (writer, critic, liaison, judge, portfolio builder) | `groq:openai/gpt-oss-120b` | The largest open model on the free plan, for the text a client reads |
| Fallbacks | `qwen3.8-27b` for both tiers | Different quota pool from the primaries |
| Local profile | Ollama `qwen3:4b`, fallback `llama3.2` | Fully offline path; slow on CPU |
| Embeddings | `BAAI/bge-base-en-v1.5` (768-d) on CPU | `nomic-embed-text-v1.5` needs remote code that broke with transformers 5 |
| Reranker | `BAAI/bge-reranker-base` on CPU | `bge-reranker-v2-m3` exhausted RAM during evaluation and crashed Postgres |

All of these are set in `agent/config.yaml`; no node names a model.

## Consequences
- The three tiers spread load over three daily quotas (see ADR 0003).
- The smaller reranker is less accurate on long passages than v2-m3; the retrieval results in
  `evals/results/` are measured with it.
- The comparison of open model configurations (quality, latency, cost) is reported in the R&D
  report once the evaluation queue has run.
