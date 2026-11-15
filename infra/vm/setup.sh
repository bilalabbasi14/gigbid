#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu VM for GigBid (docs/RUNBOOK.md, section 3).
# Run on the VM as the login user (it uses sudo):
#   bash setup.sh <dns-name>          e.g. bash setup.sh gigbid-yourname.eastus.cloudapp.azure.com
# It adds swap, installs Docker, clones the repository to /opt/gigbid and creates
# /opt/gigbid/.env.production with random secrets. Then fill DATABASE_URL and GROQ_API_KEY in that
# file and run infra/vm/deploy.sh.
set -euo pipefail
SITE="${1:?usage: setup.sh <dns-name of this VM>}"
REPO="${GIGBID_REPO:-https://github.com/bilalabbasi14/gigbid.git}"
DIR=/opt/gigbid

# The stack needs about 3.5 GB at peak; swap keeps a 4 GB VM from running out during builds.
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab > /dev/null
fi

if ! command -v docker > /dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

sudo mkdir -p "$DIR"
sudo chown "$USER" "$DIR"
[ -d "$DIR/.git" ] || git clone --depth 1 "$REPO" "$DIR"

ENVF="$DIR/.env.production"
if [ ! -f "$ENVF" ]; then
  cp "$DIR/infra/vm/env.production.example" "$ENVF"
  chmod 600 "$ENVF"
fi

set_if_empty() {  # key value: fill a key only when it has no value yet
  if grep -qE "^$1=$" "$ENVF"; then
    sed -i "s|^$1=$|$1=$2|" "$ENVF"
  fi
}
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
set_if_empty SITE_ADDRESS "$SITE"
set_if_empty WEB_BASE_URL "https://$SITE"
set_if_empty APP_SECRET_KEY "$(rand 48)"
set_if_empty TOKEN_ENCRYPTION_KEY "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
set_if_empty GIGSIM_API_TOKEN "$(rand 24)"
set_if_empty MCP_BEARER_TOKEN "$(rand 24)"
set_if_empty REVIEWER_PASSWORD "$(rand 12)"

echo
echo "Set up. Now fill DATABASE_URL and GROQ_API_KEY in $ENVF (nano $ENVF), then run:"
echo "  newgrp docker   # or log out and in, so docker works without sudo"
echo "  bash $DIR/infra/vm/deploy.sh"
echo "Reviewer login: $(grep '^REVIEWER_EMAIL=' "$ENVF" | cut -d= -f2) (password in $ENVF)"
