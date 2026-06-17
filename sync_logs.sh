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
  --exclude="*_K_5M_combined.csv" \
  --exclude="*_K_5M_EXT_combined.csv" \
  "$VPS:~/moomoo/logs/" ./logs/
# The VPS's own rolling candle archive (scripts/fetch_daily_archive.py) is excluded above —
# it's small/operational and would otherwise land next to (or be confused with) the much
# larger local multi-year combined CSVs of the same base name. Pull it manually if ever needed:
#   rsync "$VPS:~/moomoo/logs/US_IWM_K_5M_EXT_combined.csv" ./logs/US_IWM_K_5M_EXT_vps.csv

echo "Sync complete."
