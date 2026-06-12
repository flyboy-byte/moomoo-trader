#!/usr/bin/env bash
# Deploy latest code to VPS and restart all moomoo services.
# Run from local machine: ./deploy.sh
set -euo pipefail

# VPS host lives in .env (VPS_HOST=user@host) — not committed, repo is public.
VPS=$(grep -E '^VPS_HOST=' .env | cut -d= -f2-)
[ -n "$VPS" ] || { echo "VPS_HOST not set in .env"; exit 1; }

echo "=== Pre-deploy checks ==="

# 1. Tests must pass before deploying
.venv/bin/python -m pytest tests/ -q || { echo "Tests failed — aborting deploy."; exit 1; }

# 2. Warn on uncommitted changes (don't block — you may want to deploy config fixes)
if ! git diff-index --quiet HEAD --; then
    echo "WARNING: uncommitted local changes (not deployed — only what's pushed to GitHub)."
fi

echo ""
echo "=== Deploying to $VPS ==="

ssh "$VPS" bash <<'REMOTE'
set -euo pipefail
cd ~/moomoo

echo "--- git pull ---"
git pull

echo "--- syntax check ---"
python3 -m compileall -q mm/ scripts/

echo "--- restarting services ---"
systemctl --user restart moomoo-paper.service
systemctl --user restart moomoo-dashboard.service

echo "--- status ---"
systemctl --user status moomoo-paper.service --no-pager -l | head -6
echo ""
systemctl --user status moomoo-dashboard.service --no-pager -l | head -6
REMOTE

echo ""
echo "Deploy complete."
