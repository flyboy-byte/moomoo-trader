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
VIX_LINE='10 13 * * 2-6 cd ~/moomoo && .venv/bin/python scripts/fetch_vix_morning.py >> logs/cron_vix.log 2>&1'
# 9:20 ET = 13:20 UTC (EDT). Runs Mon-Fri to classify pre-market regime before open.
REGIME_LINE='20 13 * * 1-5 cd ~/moomoo && .venv/bin/python scripts/classify_regime.py >> logs/cron_regime.log 2>&1'

# Bug fix 2026-06-17: the old idempotency check matched on script filename
# substring only, not the full line. If a line's schedule/args were ever
# hand-edited on the VPS, re-running this would see the filename match and
# silently skip re-adding the corrected line, leaving the stale one in
# place — this already happened once this session (weekly_report.py's
# wrong UTC-vs-ET schedule had to be fixed via raw crontab editing because
# the installer wouldn't touch it). Now: exact-line match = skip (already
# correct); filename match but different line = remove the stale line and
# install the corrected one (self-heal); no match = add.
echo "=== Installing cron on $VPS ==="
ssh "$VPS" bash <<REMOTE
set -euo pipefail
CURRENT=\$(crontab -l 2>/dev/null || true)
NEW="\$CURRENT"

update_line() {
  pattern="\$1"
  newline="\$2"
  if echo "\$NEW" | grep -qF "\$newline"; then
    echo "  exact line already present — skipping: \$pattern"
    return
  fi
  if echo "\$NEW" | grep -qF "\$pattern"; then
    echo "  stale line found for \$pattern — replacing with corrected schedule/args"
    NEW=\$(echo "\$NEW" | grep -vF "\$pattern")
  else
    echo "  adding new line for \$pattern"
  fi
  NEW="\$NEW
\$newline"
}

update_line "fetch_daily_archive.py" "$DAILY_LINE"
update_line "weekly_report.py" "$WEEKLY_LINE"
update_line "fetch_vix_morning.py" "$VIX_LINE"
update_line "classify_regime.py" "$REGIME_LINE"

echo "\$NEW" | crontab -
echo ""
echo "=== Final crontab ==="
crontab -l
REMOTE
