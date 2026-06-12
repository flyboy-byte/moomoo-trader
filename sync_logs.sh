#!/usr/bin/env bash
# Pull production logs from VPS to local logs/.
# Run from local machine: ./sync_logs.sh
# Safe: --update skips files newer on local (never overwrites local research outputs).
set -euo pipefail

# VPS host lives in .env (VPS_HOST=user@host) — not committed, repo is public.
VPS=$(grep -E '^VPS_HOST=' .env | cut -d= -f2-)
[ -n "$VPS" ] || { echo "VPS_HOST not set in .env"; exit 1; }

echo "=== Syncing logs from $VPS ==="
rsync -avz --update \
  --exclude="backtest_*.log" \
  --exclude="research_*.log" \
  --exclude="multi_backtest_*.log" \
  --exclude="sweep_*.log" \
  "$VPS:~/moomoo/logs/" ./logs/

echo "Sync complete."
