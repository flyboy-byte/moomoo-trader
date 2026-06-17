#!/usr/bin/env bash
# Idempotently install the daily archive + weekly report cron jobs on the VPS.
# Safe to re-run: only appends lines not already present in the VPS user crontab.
#
# VPS runs UTC (confirmed via `ssh $VPS date`). 8pm ET close ≈ 00:00 UTC during EDT
# (off by ~1hr in winter EST — harmless, both jobs just run a bit earlier relative
# to close). Daily archive runs Tue-Sat UTC to capture Mon-Fri ET trading closes;
# weekly report runs Saturday UTC, right after that week's Friday-close archive run.
set -euo pipefail

VPS=$(grep -E '^VPS_HOST=' .env | cut -d= -f2-)
[ -n "$VPS" ] || { echo "VPS_HOST not set in .env"; exit 1; }

DAILY_LINE='15 0 * * 2-6 cd ~/moomoo && .venv/bin/python scripts/fetch_daily_archive.py >> logs/cron_premarket.log 2>&1'
WEEKLY_LINE='30 0 * * 6 cd ~/moomoo && .venv/bin/python scripts/weekly_report.py >> logs/cron_weekly.log 2>&1'

echo "=== Installing cron on $VPS ==="
ssh "$VPS" bash <<REMOTE
set -euo pipefail
CURRENT=\$(crontab -l 2>/dev/null || true)
NEW="\$CURRENT"
if ! echo "\$CURRENT" | grep -qF "fetch_daily_archive.py"; then
  NEW="\$NEW
$DAILY_LINE"
  echo "Adding daily archive cron line."
else
  echo "Daily archive cron line already present — skipping."
fi
if ! echo "\$CURRENT" | grep -qF "weekly_report.py"; then
  NEW="\$NEW
$WEEKLY_LINE"
  echo "Adding weekly report cron line."
else
  echo "Weekly report cron line already present — skipping."
fi
echo "\$NEW" | crontab -
echo ""
echo "=== Final crontab ==="
crontab -l
REMOTE
