# Operational Workflow

# NOTE: $VPS_HOST below = the VPS ssh target (user@ip). It lives in .env as VPS_HOST= — not committed.

Two environments: **local** (dev + paper trading on laptop) and **VPS** (always-on live runner).
Code changes always flow: local → GitHub → VPS. Never edit code directly on VPS.

**VPS layout (since 2026-10-17):** OpenD, the paper runner and the dashboard are *system* units
(`moomoo-opend`, `moomoo-paper`, `moomoo-dashboard`) running as the sandboxed user `moomoo`. Code runs from the
read-only copy `/opt/moomoo`; `~/moomoo` on the VPS is only the git clone. Config, logs and kill switches live in
`/var/lib/moomoo/root/`. The six cron jobs are now `moomoo-job-*` systemd timers. `sudo` over SSH needs the
`vps-sudo` window open first. Full detail: `~/projects/extraction/docs/flyboybyte-vps-architecture.md`.

---

## Local — Trading Session

```bash
./mask_sleep.sh                        # block system suspend
./start.sh                             # start OpenD + paper runner
python scripts/web_dashboard.py        # monitor at http://localhost:8080
```

At market close (4 PM ET):
```bash
python scripts/eod_summary.py          # print session recap
python scripts/eod_summary.py --post-discord  # optional: post to Discord
./stop.sh                              # stop paper runner
./unmask_sleep.sh                      # re-enable suspend
```

**Kill switch:** `touch STOP_TRADING.txt` pauses runner instantly. `rm STOP_TRADING.txt` resumes.

---

## Local — Development

```bash
source .venv/bin/activate
python -m pytest tests/ -q            # run tests (must stay green)
git add <files>
git commit -m "..."
git push
```

Then deploy to VPS (run `vps-sudo` in your own terminal first; `deploy.sh` runs locally and does the
push, `git pull`, rsync into `/opt/moomoo` and service restart over SSH):
```bash
./deploy.sh
```

**Rules:**
- Never push without tests passing
- `.env` is gitignored — sync separately if it changes (see below)
- Never commit secrets, credentials, or real trade logs

---

## Local — Config Changes

The VPS `.env` (`/var/lib/moomoo/root/.env`, owner `moomoo`, mode 600) is no longer readable or writable by the
`ubuntu` login, so it can't be `scp`'d. Edit it through the dashboard config editor, or by hand with
`sudo -u moomoo`, then `sudo systemctl restart moomoo-paper`.

---

## Local — Research & Backtesting

```bash
source .venv/bin/activate
python scripts/run_backtest.py --latest
python scripts/walk_forward.py --latest
python scripts/research.py --latest
python scripts/sweep.py --latest
python scripts/sweep_signals.py --latest
python scripts/multi_backtest.py logs/US_IWM_K_5M*.csv logs/US_SPY_K_5M*.csv
python scripts/eod_summary.py --date 2026-06-01   # review past session
```

Historical data lives in `logs/US_*.csv` (gitignored). Fetch fresh candles:
```bash
python scripts/fetch_candles.py --symbol US.IWM --start 2025-01-01 --end 2026-06-01
```

---

## VPS — OpenD Login

OpenD logs in unattended from `/opt/moomoo-opend/OpenD.xml` (root:moomoo 640; edit with sudo). It re-logs in after
the scheduled 04:00 UTC reboot. Check with `sudo journalctl -u moomoo-opend -f` (look for `qotlogined: true`).
Start order is OpenD, then paper, then dashboard. Don't restart OpenD casually or during market hours.

### SMS / captcha verification (when Moomoo requires it)

Happens after repeated failed logins or when Moomoo flags the IP:
```bash
ssh $VPS_HOST
telnet 127.0.0.1 22222
```
```
relogin
input_phone_verify_code -code=XXXXXX
```
You should see `Login successful`; the paper runner reconnects within 60s. If phone verify says "not available
during current period", use `req_pic_verify_code` instead. It writes `PicVerifyCode.png` under
`/var/lib/moomoo/.com.moomoo.OpenD/*/` (readable only with sudo); copy it out, view it, then
`input_pic_verify_code -code=XXXXXX`.

---

## VPS — Daily Operations

```bash
ssh $VPS_HOST

# Status (no sudo needed)
systemctl is-active moomoo-opend moomoo-paper moomoo-dashboard
systemctl list-timers 'moomoo-job-*'

# Live logs (sudo for journal; log files below are readable without it)
sudo journalctl -u moomoo-paper -f
tail -f /var/lib/moomoo/root/logs/paper_US_IWM_$(date +%Y-%m-%d).jsonl

# Deploy: run ./deploy.sh from the LOCAL machine (not on the VPS)

# Restart
sudo systemctl restart moomoo-paper

# Kill switch (the dashboard also toggles these)
sudo -u moomoo touch /var/lib/moomoo/root/STOP_TRADING.txt   # pause trading
sudo -u moomoo rm /var/lib/moomoo/root/STOP_TRADING.txt      # resume trading
```

The dashboard's "restart runner" button does not work in this layout (needs a polkit rule the owner has not
approved); restart over SSH instead.

---

## VPS — Sync Logs to Local

```bash
./sync_logs.sh      # rsync from /var/lib/moomoo/root/logs/, no sudo needed
```

Then run local analysis tools against the synced data.

---

## Strategy Mode

Controlled by `STRATEGY_MODE` in `.env`:

| Mode | Entry condition | Use for |
|------|----------------|---------|
| `strict` | BB touch + KDJ cross + bonus≥2 | Production (default) |
| `permissive` | BB touch + bonus≥1 | Validating order execution |

Switch and restart:
```bash
# Local: edit .env: STRATEGY_MODE=strict, then
systemctl --user restart moomoo-paper.service
# VPS: edit /var/lib/moomoo/root/.env via the dashboard config editor, then
ssh $VPS_HOST 'sudo systemctl restart moomoo-paper'
```

---

## File Locations

| File | Local | VPS |
|------|-------|-----|
| Code | `~/projects/moomoo/` | `/opt/moomoo/` (runtime, read-only); `~/moomoo/` is the git clone |
| Config | `~/projects/moomoo/.env` | `/var/lib/moomoo/root/.env` (moomoo-only) |
| OpenD binary | `~/apps/moomoo-opend/` (AppImage) | `/opt/moomoo-opend/` (headless) |
| OpenD config | n/a (GUI) | `/opt/moomoo-opend/OpenD.xml` |
| Logs (JSONL) | `~/projects/moomoo/logs/` | `/var/lib/moomoo/root/logs/` (group `moomoo-logs`) |
| Kill switches | project root | `/var/lib/moomoo/root/STOP_*.txt` |
| systemd units | `~/.config/systemd/user/` | system units `moomoo-*` + `moomoo-job-*.timer` |
