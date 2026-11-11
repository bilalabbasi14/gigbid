# ADR 0001: Stack and infrastructure choices

**Status:** accepted · **Date:** 2026-11-11

## Context
GigBid must run end to end on the open-model profile, on a laptop with 8 GB RAM and no CUDA GPU,
and deploy to a free host. The assignment fixes the broad stack (Python 3.11+, LangGraph,
langchain-mcp-adapters, MCP Python SDK, FastAPI, Next.js, Postgres, Redis, one vector store, one
tracing tool) but leaves the concrete choices open.

## Decisions
| Area | Choice | Why |
|---|---|---|
| Package manager | `uv` with a committed `uv.lock` | Fast, reproducible, pins every version as the brief requires |
| Vector store | **pgvector** inside the Postgres service | One fewer container on an 8 GB machine; metadata filters and hybrid retrieval in SQL; corpus is ~10k chunks |
| Background worker | **Arq** on Redis | Async-native (matches FastAPI + LangGraph), cron support, idempotent job keys, tiny footprint |
| Tracing | **LangSmith** (free tier) | Self-hosted Langfuse v3 needs ClickHouse + object storage; LangSmith integrates with LangGraph natively and gives per-node token/cost |
| Hosted open models | **Groq** (gpt-oss-120b / gpt-oss-20b / llama-3.1-8b) with OpenRouter free models as fallback | Free hosts have no GPU; the brief allows hosted open-weight providers; Groq's latency keeps p95 low |
| Local option | Ollama `qwen3:4b` + `nomic-embed-text`, as an optional compose profile | Honest local path for cheap nodes; too slow for Writer/Critic on CPU |
| Embeddings / reranker | `nomic-embed-text-v1.5`, `bge-reranker-v2-m3` via sentence-transformers on CPU (superseded by ADR 0004: `bge-base-en-v1.5`, `bge-reranker-base`) | Open models in both profiles as required |
| Frontend | Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, `openapi-typescript` client | Required screens are data-heavy dashboards; generated client enforces the typed contract |
| Auth | Own users table, Argon2, JWT cookie, Fernet-encrypted token store | Multi-user without an external identity provider |

## Consequences
- `docker compose up` starts Postgres(pgvector), Redis, GigSim, MCP servers, API, worker, web;
  Ollama only with `--profile local-llm`.
- Model names are never in code: `agent/config.yaml` maps node → tier → provider model.
