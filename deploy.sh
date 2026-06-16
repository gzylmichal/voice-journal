#!/usr/bin/env bash
#
# deploy.sh — push this repo's CODE to the VPS as ONE consistent tree.
#
# Why: copying files one-at-a-time causes version skew (e.g. a new
# voice_journal.py against a stale pipeline/config.py → the NTFY_TOPIC bug).
# This stages the whole working tree, then installs it in a single rsync.
#
# It NEVER touches your secrets or runtime data: .env, venv, inbox/, buffer/,
# archive/, reports/, logs, and gcal tokens are all excluded.
#
# Usage:
#   ./deploy.sh                  # defaults to michal@vps-main
#   ./deploy.sh user@host        # override target
#
set -euo pipefail

VPS="${1:-vps}"   # SSH config alias (Host vps → 91.98.122.180); override: ./deploy.sh user@host
APP_DIR="/opt/voice-journal"
STAGE="/tmp/vj-deploy"

# Excludes keep staging to clean code only — secrets/runtime never leave the VPS.
EXCLUDES=(
  --exclude '.git'
  --exclude '.env'
  --exclude '.env.*'
  --exclude 'venv'
  --exclude '__pycache__'
  --exclude '.pytest_cache'
  --exclude '*.log'
  --exclude 'inbox'
  --exclude 'buffer'
  --exclude 'archive'
  --exclude 'reports'
  --exclude 'gcal_token.json'
  --exclude 'gcal_credentials.json'
  --exclude 'backfill_done.txt'
  --exclude '*.bak'
)

echo "==> [1/3] Staging clean code to ${VPS}:${STAGE}"
rsync -av --delete "${EXCLUDES[@]}" ./ "${VPS}:${STAGE}/"

echo "==> [2/3] Installing into ${APP_DIR} + restarting receiver (sudo)"
# No --delete on the install: leaves VPS-only runtime data untouched.
# Staging already contains no secrets/runtime, so .env and venv are safe.
ssh -t "${VPS}" "
  set -e
  sudo rsync -av ${STAGE}/ ${APP_DIR}/
  sudo chown -R journal:journal ${APP_DIR}
  sudo systemctl restart voice-journal-receiver
"

echo "==> [3/3] Smoke test on the VPS"
ssh -t "${VPS}" "cd ${APP_DIR} && sudo -u journal ${APP_DIR}/venv/bin/python3 smoke_test.py"

echo "==> Deploy complete. Verify: no NTFY_TOPIC warnings above; set NTFY_TOPIC in .env to enable pushes."
