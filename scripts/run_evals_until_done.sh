#!/usr/bin/env bash
# Rerun the evaluation queue until no step is left partial, waiting between attempts while the
# free tier's daily caps refill (Groq frees tokens 24 hours after they were used). Each attempt
# resumes from the saved rows, so a capped attempt costs a request or two per step.
#   bash scripts/run_evals_until_done.sh [first-start "YYYY-mm-dd HH:MM"] [minutes between] [stop "YYYY-mm-dd HH:MM"]
set -uo pipefail
cd "$(dirname "$0")/.."
FIRST="${1:-now}"
EVERY_MIN="${2:-90}"
STOP="${3:-}"
LOG=data/processed/eval_logs/queue_until_done.log
mkdir -p "$(dirname "$LOG")"

wait_until() {  # sleep until a wall-clock time
  local target now
  target=$(date -d "$1" +%s) || return 1
  now=$(date +%s)
  if [ "$target" -gt "$now" ]; then sleep $((target - now)); fi
}

[ "$FIRST" = "now" ] || wait_until "$FIRST"
attempt=0
while true; do
  attempt=$((attempt + 1))
  out=$(mktemp)
  echo "=== attempt $attempt $(date '+%Y-%m-%d %H:%M') ===" | tee -a "$LOG"
  bash scripts/run_evals.sh > "$out" 2>&1
  cat "$out" >> "$LOG"
  if ! grep -qE "PARTIAL|FAIL (decisions|x3|proposals|injection|multiagent|judge)" "$out"; then
    echo "=== all steps finished $(date '+%Y-%m-%d %H:%M') ===" | tee -a "$LOG"
    rm -f "$out"
    exit 0
  fi
  grep -E "PARTIAL|FAIL" "$out" | sed 's/^/  /' | tee -a "$LOG"
  rm -f "$out"
  if [ -n "$STOP" ] && [ "$(date +%s)" -ge "$(date -d "$STOP" +%s)" ]; then
    echo "=== stop time reached; partial steps stay partial ===" | tee -a "$LOG"
    exit 3
  fi
  sleep $((EVERY_MIN * 60))
done
