#!/usr/bin/env bash
# Deploy latest code to VPS and restart all moomoo services.
# Run from local machine: ./deploy.sh
# Or run directly on VPS: ssh ubuntu@<host> 'cd ~/moomoo && bash deploy.sh'
set -euo pipefail

VPS="ubuntu@51.81.80.126"
REMOTE_DIR="~/moomoo"

echo "=== Deploying to $VPS ==="

ssh "$VPS" bash <<'REMOTE'
set -euo pipefail
cd ~/moomoo

echo "--- git pull ---"
git pull

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
