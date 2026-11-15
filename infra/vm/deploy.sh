#!/usr/bin/env bash
# Deploy the latest main on the VM: pull, rebuild, restart, wait until healthy.
# Idempotent; the Deploy workflow runs it over SSH on every push to main.
#   bash /opt/gigbid/infra/vm/deploy.sh
set -euo pipefail
DIR=/opt/gigbid
cd "$DIR"
git fetch --quiet --depth 1 origin main
git reset --quiet --hard origin/main   # this checkout only serves deploys
COMPOSE=(docker compose -f infra/vm/docker-compose.yml --env-file .env.production)
"${COMPOSE[@]}" up -d --build --remove-orphans
docker image prune -f > /dev/null

echo "waiting for the app to become healthy (first start indexes the personas, up to 10 minutes)"
for _ in $(seq 1 80); do
  if "${COMPOSE[@]}" exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=10)" 2> /dev/null; then
    echo "healthy: https://$(grep '^SITE_ADDRESS=' .env.production | cut -d= -f2)"
    exit 0
  fi
  sleep 15
done
echo "the app did not become healthy; recent logs:" >&2
"${COMPOSE[@]}" logs --tail 80 app >&2
exit 1
