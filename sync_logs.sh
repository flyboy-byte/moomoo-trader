#!/usr/bin/env bash
# Pull production logs from VPS to local logs/.
# Run from local machine: ./sync_logs.sh
# Safe: --update skips files newer on local (never overwrites local research outputs).
set -euo pipefail

VPS="ubuntu@51.81.80.126"

echo "=== Syncing logs from $VPS ==="
rsync -avz --update \
  --exclude="backtest_*.log" \
  --exclude="research_*.log" \
  --exclude="multi_backtest_*.log" \
  --exclude="sweep_*.log" \
  "$VPS:~/moomoo/logs/" ./logs/

echo "Sync complete."
