# VPS Agent Context

This file is for Claude Code running on the VPS (51.81.80.126). Read this before doing anything.

## Your role

You are the **always-on runner**, not the dev environment. Your job:
- Monitor services and logs
- Diagnose issues without touching code
- Answer questions about what the live runner is doing

**Never edit code directly on the VPS.** All code changes happen on the local machine, get committed and pushed to GitHub, then deployed here via `./deploy.sh` (`git pull` + service restart).

## Architecture

```
Local machine (dev) → GitHub → VPS (runner)
```

- Local: dev, backtesting, research, strategy tuning
- VPS: live paper runner only

## Services

```bash
systemctl --user status moomoo-opend.service   # OpenD headless API gateway
systemctl --user status moomoo-paper.service   # paper trading loop
```

Logs:
```bash
journalctl --user -u moomoo-opend.service -f
journalctl --user -u moomoo-paper.service -f
tail -f ~/moomoo/logs/paper_US_IWM_$(date +%Y-%m-%d).jsonl
```

## Current state (2026-06-01)

- OpenD: credentials set in ~/opend/OpenD.xml. Was in 30-min login lockout from too many failed restart attempts. Start it after lockout clears.
- Paper runner: not started yet, waiting on OpenD
- UFW: enabled. SSH (22) + Flask (8080) open. Port 11111 (OpenD API) blocked externally — localhost only.
- Strategy mode: permissive (BB touch + bonus≥1) — to validate order execution flow. Switch to strict once a trade fires end-to-end.

## Deploy new code from local

```bash
cd ~/moomoo && ./deploy.sh
```

## Kill switch

```bash
touch ~/moomoo/STOP_TRADING.txt   # pause trading immediately
rm ~/moomoo/STOP_TRADING.txt      # resume
```

## Security rules — never violate

- TRD_ENV=SIMULATE always
- LIVE_TRADING_ENABLED=false always
- Do not store secrets in code or git

## What to build next (do this on local, not here)

1. Fetch fresh candles (historical data stops 2025-05-30, now June 2026)
2. Flask web dashboard — reads JSONL, serves at :8080
3. Re-enable unlock_trade in mm/paper.py for headless OpenD
4. Entry window sweep script
