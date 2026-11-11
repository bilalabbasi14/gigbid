#!/usr/bin/env bash
# Process supervisor for the single-container deployment (infra/docker/space.Dockerfile).
# Starts Redis, GigSim (if local), seeds the reviewer login and indexes, then the API, worker and
# web server. If any long-running process exits, the container exits so the host restarts it.
set -euo pipefail
cd /app

: "${DATABASE_URL:?DATABASE_URL must point at a Postgres database with the pgvector extension}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export GIGSIM_BASE_URL="${GIGSIM_BASE_URL:-http://127.0.0.1:8081}"
export GIGSIM_DB_PATH="${GIGSIM_DB_PATH:-/app/data/processed/gigsim.db}"
export WEB_BASE_URL="${WEB_BASE_URL:-http://localhost:${PORT}}"

pids=()
start() { echo "[serve_all] starting $1"; shift; "$@" & pids+=("$!"); }

if [[ "$REDIS_URL" == redis://127.0.0.1* ]]; then
  redis-server --save "" --appendonly no --port 6379 --daemonize yes --loglevel warning
fi

if [[ "$GIGSIM_BASE_URL" == http://127.0.0.1:8081* ]]; then
  start gigsim uvicorn gigsim.app:app --host 127.0.0.1 --port 8081 --log-level warning
fi

# idempotent: reviewer login, saved searches, and persona corpora indexed into pgvector
python -m scripts.seed --persona "${REVIEWER_PERSONA:-ai_ml}" || echo "[serve_all] seed failed; continuing"

start api uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --proxy-headers --log-level info
if [[ "${RUN_WORKER:-1}" == "1" ]]; then
  start worker arq worker.settings.WorkerSettings
fi
start web env PORT="$PORT" HOSTNAME=0.0.0.0 node web/server.js

trap 'kill "${pids[@]}" 2>/dev/null || true' TERM INT
wait -n "${pids[@]}"
echo "[serve_all] a process exited; stopping the container so the host restarts it"
kill "${pids[@]}" 2>/dev/null || true
exit 1
