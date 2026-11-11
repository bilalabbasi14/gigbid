#!/usr/bin/env bash
# Sequential evaluation queue (free-tier model limits allow only one LLM-heavy run at a time).
# Each step logs to data/processed/eval_logs/<step>.log and the queue continues if a step fails.
# Requires: Postgres with the persona index, and GigSim on GIGSIM_BASE_URL for the outcome steps.
#   bash scripts/run_evals.sh [step ...]      (default: all steps in order)
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1 OMP_NUM_THREADS=4 LANGSMITH_TRACING=false
LOGS=data/processed/eval_logs
mkdir -p "$LOGS"

step() {
  local name="$1"; shift
  echo "[$(date +%H:%M:%S)] >>> $name"
  if uv run python -m "$@" > "$LOGS/$name.log" 2>&1; then
    echo "[$(date +%H:%M:%S)] ok  $name: $(tail -1 "$LOGS/$name.log")"
  else
    echo "[$(date +%H:%M:%S)] FAIL $name (see $LOGS/$name.log): $(tail -1 "$LOGS/$name.log")"
  fi
}

# untagged retrieval steps (rag_full, rag_ctx) write rag_summary.json, so they run last, after any
# earlier full retrieval run has finished writing it
ALL=(rag_ctx_ingest rag_subset decisions proposals_v0 proposals_v2 proposals_best x3 injection multiagent judge_export judge rag_full rag_ctx tables)
STEPS=("${@:-${ALL[@]}}")
for s in "${STEPS[@]}"; do
  case "$s" in
    rag_full)       step rag_full evals.runners.rag_eval --variants v0_naive,v9_skill_graph ;;  # V2-V8 come from the full run already in progress
    rag_ctx_ingest) step rag_ctx_ingest rag.ingest.cli --persona ai_ml --persona fullstack --persona data_analyst --contextual ;;
    rag_ctx)        step rag_ctx evals.runners.rag_eval --variants v6_contextual ;;
    rag_subset)     step rag_subset evals.runners.rag_eval --variants v0_naive,v2_hybrid,v3_rerank,v1_decompose,v7_hyde,best --limit 20 --tag _subset20 ;;
    decisions)      step decisions evals.runners.decision_eval --per-persona 20 ;;
    proposals_v0)   step proposals_v0 evals.runners.proposal_eval --per-persona 4 --variant v0_naive --gigsim --out proposal_eval_v0_naive ;;
    proposals_v2)   step proposals_v2 evals.runners.proposal_eval --per-persona 4 --variant v2_hybrid --gigsim --out proposal_eval_v2_hybrid ;;
    proposals_best) step proposals_best evals.runners.proposal_eval --per-persona 4 --variant best --gigsim --out proposal_eval_best ;;
    x3)             step x3 evals.runners.x3_eval ;;
    injection)      step injection evals.runners.injection_eval --per-family 1 ;;
    multiagent)     step multiagent evals.runners.multiagent_compare --jobs 30 --gigsim ;;
    judge_export)   step judge_export evals.runners.judge_calibration export --n 30 ;;
    judge)          step judge evals.runners.judge_calibration judge ;;
    tables)         step tables evals.runners.results_table ;;
    *) echo "unknown step $s" ;;
  esac
done
echo "[$(date +%H:%M:%S)] queue finished"
