# VPS Agent Context

This file is for Claude Code running on the VPS. Read this before doing anything.

## Your role

You are the **always-on runner**, not the dev environment. Your job:
- Monitor services, logs, and cron jobs
- Diagnose issues without touching code
- Answer questions about what the live runner is doing

**Never edit code directly on the VPS.** All code changes happen on the local machine, get committed and pushed to GitHub, then deployed here via `./deploy.sh` (`git pull` + service restart).

## Architecture

```
Local machine (dev) → GitHub → VPS (runner)
```

- Local: dev, backtesting, research, strategy tuning
- VPS: live paper runner + dashboard + daily/weekly cron jobs only

## Services (3, all systemd user services, Restart=always)

```bash
systemctl --user status moomoo-opend.service       # OpenD headless API gateway
systemctl --user status moomoo-paper.service        # paper trading loop
systemctl --user status moomoo-dashboard.service    # web dashboard, :8080
```

Logs:
```bash
journalctl --user -u moomoo-opend.service -f
journalctl --user -u moomoo-paper.service -f
tail -f ~/moomoo/logs/paper_US_IWM_$(date +%Y-%m-%d).jsonl
```

## Cron jobs (VPS runs UTC — see `scripts/install_cron.sh` for the idempotent installer)

```bash
crontab -l
```
Expected (as of 2026-06-17):
```
15 0 * * 2-6   fetch_daily_archive.py    # rolling RTH+EXT candle archive
30 0 * * 6     weekly_report.py          # gate-progress + premarket Discord report
10 13 * * 2-6  fetch_vix_morning.py      # VIX shadow-logger, observational only
```

## Current state (as of 2026-06-17/18)

Multi-strategy paper runner has been live continuously since early June 2026:
`bb_kdj` + `orb` (long+short) + `vwap_pb` on SPY/QQQ/IWM, strategy mode `strict`.
`ORB_SHORTS_ENABLED=true` and `STOP_SHORTS.txt` was removed 2026-06-17 — ORB shorts
fire live in SIMULATE now (see `docs/strategy_graveyard.md`). 178+ tests pass on local.
For exact current numbers/config, don't trust this file's snapshot — run
`./scripts/verify.sh` or check `docs/PROJECT_MAP.md` / `docs/strategy_graveyard.md`,
which are kept current as the actual source of truth.

## Deploy new code from local

```bash
cd ~/moomoo && ./deploy.sh
```

## Kill switches (runtime, no restart needed)

```bash
touch ~/moomoo/STOP_TRADING.txt   # pause ALL entries immediately (exits still fire)
rm ~/moomoo/STOP_TRADING.txt      # resume

touch ~/moomoo/STOP_SHORTS.txt    # disable ORB short entries only
rm ~/moomoo/STOP_SHORTS.txt       # re-enable (currently removed — shorts are live)
```

## Security rules — never violate

- TRD_ENV=SIMULATE always
- LIVE_TRADING_ENABLED=false always
- Do not store secrets in code or git — VPS_HOST and webhook URLs live in `.env` only

## What to build next

Don't trust a stale list here — `docs/strategy_graveyard.md`'s "On Hold" section and
CLAUDE.md's "Current priorities" are the living backlog, kept current as work happens.
This section intentionally left without a checklist to avoid going stale again.
