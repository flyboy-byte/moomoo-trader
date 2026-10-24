#!/usr/bin/env bash
# Deploy latest code to VPS and restart all moomoo services.
# Run from local machine: ./deploy.sh
set -euo pipefail

# VPS host lives in .env (VPS_HOST=user@host) — not committed, repo is public.
VPS=$(grep -E '^VPS_HOST=' .env | cut -d= -f2-)
[ -n "$VPS" ] || { echo "VPS_HOST not set in .env"; exit 1; }

echo "=== Pre-deploy checks ==="

# 1. Warn on uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "WARNING: uncommitted local changes (not deployed — only what's pushed to GitHub)."
fi

# 2. Tests must pass before deploying
.venv/bin/python -m pytest tests/ -q || { echo "Tests failed — aborting deploy."; exit 1; }

# 3. Push to GitHub
echo "--- git push ---"
git push origin master

echo ""
echo "=== Deploying to $VPS ==="

# Since 2026-10-17 production is system units under user `moomoo`, running from /opt/moomoo.
# The sudo steps below need the vps-sudo window open first (run `vps-sudo` in your own terminal).
ssh "$VPS" bash <<'REMOTE'
set -euo pipefail
cd ~/moomoo

echo "--- git pull ---"
git pull

echo "--- syntax check ---"
python3 -m compileall -q mm/ scripts/

echo "--- sync to /opt/moomoo (runtime copy, read-only to the service user) ---"
sudo rsync -a --delete --exclude __pycache__ ~/moomoo/mm ~/moomoo/scripts ~/moomoo/site ~/moomoo/docs /opt/moomoo/
sudo cp ~/moomoo/requirements.txt ~/moomoo/pyproject.toml /opt/moomoo/
sudo chown -R ubuntu:moomoo /opt/moomoo
sudo chmod -R u=rwX,g=rX,o= /opt/moomoo

echo "--- restarting services ---"
sudo systemctl restart moomoo-paper moomoo-dashboard
sleep 3

echo "--- status ---"
systemctl is-active moomoo-paper moomoo-dashboard
REMOTE

echo ""
echo "Deploy complete."
