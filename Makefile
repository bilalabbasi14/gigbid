.PHONY: help install dev api web worker gigsim mcp test test-unit test-contract test-integration \
        lint fmt typecheck eval eval-rag eval-decisions eval-outcomes eval-smoke seed ingest demo \
        demo-single ci-checks up down logs openapi-client

PY ?= uv run
COMPOSE ?= docker compose -f infra/docker-compose.yml

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install Python deps (uv) and web deps
	uv sync --all-extras
	cd apps/web && npm install

dev:  ## Start Postgres + Redis + GigSim in Docker, then API (reload) and web dev server
	$(COMPOSE) up -d postgres redis gigsim
	$(MAKE) -j2 api web

api:  ## Run FastAPI with reload
	$(PY) uvicorn apps.api.main:app --reload --port 8000

web:  ## Run Next.js dev server
	cd apps/web && npm run dev

worker:  ## Run the Arq worker (scheduled scouting + long graph runs)
	$(PY) arq worker.settings.WorkerSettings

gigsim:  ## Run the local GigSim marketplace simulator
	$(PY) uvicorn gigsim.app:app --port 8081

mcp:  ## Run the three MCP servers over streamable HTTP (ports 8101-8103)
	$(PY) python -m mcp_servers.run_all

test:  ## Unit + contract tests
	$(PY) pytest tests/unit tests/contract

test-unit:  ## Unit tests only
	$(PY) pytest tests/unit

test-contract:  ## MCP schema snapshot tests
	$(PY) pytest tests/contract

test-integration:  ## Integration tests (needs services running)
	$(PY) pytest tests/integration -m integration

lint:  ## Ruff lint + repo policy checks
	$(PY) ruff check .
	$(PY) ruff format --check .
	$(PY) python scripts/ci_checks.py

fmt:  ## Auto-format
	$(PY) ruff format .
	$(PY) ruff check --fix .

typecheck:  ## mypy
	$(PY) mypy agent rag mcp_servers apps/api worker

ci-checks:  ## Repo policy checks only (secrets, prompts, gigsim lock, README numbers)
	$(PY) python scripts/ci_checks.py

eval:  ## Full evaluation: retrieval, decisions, GigSim outcomes -> evals/results/*.json
	$(PY) python -m evals.runners.rag_eval
	$(PY) python -m evals.runners.decision_eval
	$(PY) python -m evals.runners.gigsim_outcomes
	$(PY) python -m evals.runners.results_table

eval-rag:  ## Retrieval metrics for every RAG variant
	$(PY) python -m evals.runners.rag_eval

eval-decisions:  ## Bid/skip, scam, price-band metrics
	$(PY) python -m evals.runners.decision_eval

eval-outcomes:  ## Fixed-job-set GigSim reply/hire rate
	$(PY) python -m evals.runners.gigsim_outcomes

eval-smoke:  ## 30-job smoke eval with CI thresholds
	$(PY) python -m evals.runners.smoke_eval

seed:  ## Seed Postgres + GigSim with personas and the reviewer login
	$(PY) python -m scripts.seed

ingest:  ## (Re)index portfolio corpora into pgvector + BM25
	$(PY) python -m rag.ingest.cli --all

demo:  ## One job end-to-end to the approval gate (no sending)
	$(PY) python -m scripts.demo

demo-single:  ## Single agent drafting one grounded proposal through MCP tools
	$(PY) python -m scripts.demo_single_agent

openapi-client:  ## Regenerate the TypeScript API client from FastAPI's OpenAPI schema
	$(PY) python -m scripts.export_openapi > apps/web/openapi.json
	cd apps/web && npm run gen:api

up:  ## docker compose up (everything)
	$(COMPOSE) up -d --build

down:  ## docker compose down
	$(COMPOSE) down

logs:  ## Tail compose logs
	$(COMPOSE) logs -f --tail=100
