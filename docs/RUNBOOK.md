# Runbook

How to start, deploy, operate and recover GigBid.

## 1. Local development

```bash
cp .env.example .env                  # fill GROQ_API_KEY and LANGSMITH_API_KEY (both free)
make install                          # uv sync + npm install
docker compose -f infra/docker-compose.yml up -d postgres redis
make gigsim                           # simulator on :8081 (separate terminal)
make seed                             # reviewer login + index the persona corpora (first run ~5 min on CPU)
make api                              # FastAPI on :8000 with the MCP servers mounted in-process
make web                              # Next.js on :3000
make worker                           # optional: scheduled scouting, pipeline sync, conversation polling
```

Sign in with `REVIEWER_EMAIL` / `REVIEWER_PASSWORD` from `.env`.

## 2. Everything in Docker

```bash
docker compose -f infra/docker-compose.yml up --build -d
docker compose -f infra/docker-compose.yml exec api python -m scripts.seed
```

Services: `postgres` (pgvector), `redis`, `gigsim`, `mcp` (the three MCP servers on 8101-8103 over
streamable HTTP with bearer auth), `api`, `worker`, `web`. `--profile local-llm` adds Ollama for
the fully offline `local` model profile. On an 8 GB machine run either the compose stack or the
local developer loop, not both.

## 3. Production deployment (public URL)

The deployed link runs the **open** profile (hosted open-weight models on Groq; embeddings and
reranker on CPU inside the container). Hosting choice and alternatives: ADR 0005.

| Piece | Where | Notes |
|---|---|---|
| App container | One Linux VM (Azure for Students, B2s: 2 vCPU, 4 GiB, plus 4 GB swap), built from `infra/docker/space.Dockerfile` | always on, no cold starts |
| HTTPS | Caddy in front of the app (`infra/vm/Caddyfile`) | Let's Encrypt certificate for the VM's DNS name, renewed automatically |
| Postgres + pgvector | Neon free plan | survives VM rebuilds; `CREATE EXTENSION vector` |
| Redis, GigSim, MCP servers | inside the app container | queue state is disposable; GigSim's database is on a volume |
| Models | Groq (open-weight models) | free plan limits per model; GigBid backs off and falls back |
| Simulated clients | `groq:openai/gpt-oss-20b` | the VM has no room for a local model |

The container runs `scripts/serve_all.sh`: Redis, GigSim, the idempotent seed (reviewer login,
saved searches, persona index), the API, the worker and the Next.js server on port 7860. If any
process exits the container exits and Docker restarts it.

**First deployment** (on the VM, once):
```bash
curl -fsSLO https://raw.githubusercontent.com/bilalabbasi14/gigbid/main/infra/vm/setup.sh
bash setup.sh <vm-dns-name>       # swap, Docker, clone to /opt/gigbid, .env.production with secrets
nano /opt/gigbid/.env.production  # fill DATABASE_URL (Neon) and GROQ_API_KEY
newgrp docker
bash /opt/gigbid/infra/vm/deploy.sh
```

**Later deployments** happen from GitHub Actions (`.github/workflows/deploy.yml`) on every push
to `main`: it runs `infra/vm/deploy.sh` over SSH (pull, rebuild, restart, wait until healthy) and
checks `LIVE_URL/api/health`. A scheduled run checks the URL every 6 hours, so an outage before the
hidden test run shows up as a failed workflow. Repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_KEY`, `LIVE_URL`.

**Settings on the VM** (`/opt/gigbid/.env.production`, from `infra/vm/env.production.example`):
`SITE_ADDRESS`, `WEB_BASE_URL`, `DATABASE_URL`, `GROQ_API_KEY`, `APP_SECRET_KEY`,
`TOKEN_ENCRYPTION_KEY`, `GIGSIM_API_TOKEN`, `MCP_BEARER_TOKEN`, `REVIEWER_EMAIL`,
`REVIEWER_PASSWORD`, `REVIEWER_PERSONA`, `GIGSIM_CLIENT_MODE`, `GIGSIM_CLIENT_LLM`; optional
`LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `GITHUB_TOKEN` (GitHub MCP for the portfolio
builder). The file is never committed and never copied into the image (`.dockerignore`).

**Operations:** logs `docker compose -f infra/vm/docker-compose.yml logs -f app`; restart
`docker compose -f infra/vm/docker-compose.yml --env-file .env.production restart app`; memory
`free -m` (we estimate the stack peaks around 3.5 GB; swap absorbs builds).

## 4. Rate limits and schedules

| Limit | Value | Where set |
|---|---|---|
| GigSim requests per token | 60 / min (simulator), GigBid stays at 20 / min per user | `agent/config.yaml` `marketplace.gigsim.max_requests_per_minute` |
| Upwork live requests | 6 / min per user | `marketplace.upwork_live.max_requests_per_minute` |
| Saved-search scouting (GigSim) | every 30 min minimum | `marketplace.gigsim.scout_interval_minutes` |
| Saved-search scouting (Upwork) | every 240 min minimum | `marketplace.upwork_live.scout_interval_minutes` |
| Worker concurrency | 2 graph runs | `worker/settings.py` |

**Why 240 minutes in live mode.** Upwork's automation guidance treats high-frequency polling as
scraping. A freelancer checking a saved search a few times a working day is ordinary use; the
worker never runs a saved search more often than every four hours in live mode, reads only through
the official MCP server, and never retries a 429 faster than the server's `Retry-After`.

## 5. Degraded mode and recovery

| Symptom | What GigBid does | What to do |
|---|---|---|
| Marketplace down (5xx, timeouts) | Adapter retries with backoff; MCP tools return "unavailable, retry after N s"; the UI shows the degraded banner; scouting skips the tick; nothing is sent | Nothing. Work resumes on the next tick. Check `/api/health` |
| Marketplace rate limited (429) | Back off for `Retry-After`; the per-user limiter keeps GigBid under the marketplace limit | Lower `max_requests_per_minute` if it recurs |
| Model provider rate limited | Retries with jittered backoff, then the node's fallback model | Wait for the daily quota or set `OPENROUTER_API_KEY` |
| A node fails repeatedly | The run moves to `needs_attention` with the reason (dead letter); other runs continue | Open the run, fix the cause, re-analyse the job |
| API restarted while a proposal waits for approval | The thread is checkpointed in Postgres; the approval reappears in the UI | Approve as normal; submission is idempotent per thread |
| Token budget exceeded | Run stops in `needs_attention` | Raise `budgets.max_tokens_per_thread` or trim the post |

**Crash-and-resume drill (viva):** analyse a job, wait for the approval screen, stop the API
(`Ctrl+C` or `docker compose restart api`), start it again, open the studio and approve. The
proposal is submitted once: the bid graph resumes from its Postgres checkpoint and the
marketplace call carries an idempotency key derived from the thread, so a retried or repeated
approval returns the stored result instead of spending Connects again.

**Kill the marketplace server (viva):** `docker compose stop gigsim` (or stop `make gigsim`). The
banner appears within 15 seconds, scouting and analysis report "marketplace unavailable",
approvals stay pending. `docker compose start gigsim` clears it.

## 6. Policy changes

Marketplace rules live in `data/policy_pack/policy.yaml` and thresholds and budgets in
`agent/config.yaml`. A rule is data: an id, a severity (`block`, `rewrite` or `warn`), a
description, the kinds of text it covers (`applies_to: [proposal, message]`) and detectors
composed from the types in `agent/policy.py` (contact details, links, keyword lists, whole
words, regex, word limits, required wording, unsupported claims). The Compliance Guard checks
every rule, the Writer and the Client Liaison receive every rule's description in their prompt,
and the Pricing Strategist never quotes below `pricing.min_hourly_usd` / `min_fixed_usd`.
Connects costs arrive with each job from the marketplace.

To apply a platform policy update:
1. Edit or add rules in `policy.yaml`; bump its `version` and `policy_version` in `config.yaml`.
2. `make test` (the pack is validated at load: an unknown detector or keyword list fails).
3. `make eval-smoke`, then rerun the evaluation queue (results of the old policy are dropped).

Only a rule that needs a new kind of detector requires code: one function in `agent/policy.py`.
