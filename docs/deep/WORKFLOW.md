# Operational Workflow

# NOTE: $VPS_HOST below = the VPS ssh target (user@ip). It lives in .env as VPS_HOST= — not committed.

Two environments: **local** (dev + paper trading on laptop) and **VPS** (always-on live runner).
Code changes always flow: local → GitHub → VPS. Never edit code directly on VPS.

---

## Local — Trading Session

```bash
./mask_sleep.sh                        # block system suspend
./start.sh                             # start OpenD + paper runner
python scripts/dashboard.py            # monitor in second terminal
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

Then deploy to VPS:
```bash
ssh $VPS_HOST 'cd ~/moomoo && ./deploy.sh'
```

Or SSH in and run it yourself:
```bash
ssh $VPS_HOST
cd ~/moomoo && ./deploy.sh
```

**Rules:**
- Never push without tests passing
- `.env` is gitignored — sync separately if it changes (see below)
- Never commit secrets, credentials, or real trade logs

---

## Local — Config Changes

When `.env` changes locally, sync to VPS:
```bash
scp /home/logan/projects/moomoo/.env $VPS_HOST:~/moomoo/.env
ssh $VPS_HOST 'systemctl --user restart moomoo-paper.service'
```

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

## VPS — First-Time OpenD Setup (one-time)

SSH in and edit the OpenD config with your Moomoo credentials:
```bash
ssh $VPS_HOST
nano ~/opend/OpenD.xml
```

Set these fields:
```xml
<login_account>your_email_or_phone</login_account>
<login_pwd_md5>your_login_password_md5</login_pwd_md5>
```

Generate MD5: `echo -n 'yourpassword' | md5sum`

Start OpenD and verify it authenticates:
```bash
systemctl --user start moomoo-opend.service
journalctl --user -u moomoo-opend.service -f   # watch for qotlogined: true
```

Once connected, start the paper runner:
```bash
systemctl --user start moomoo-paper.service
journalctl --user -u moomoo-paper.service -f
```

---

## VPS — OpenD SMS Verification (when Moomoo requires it)

Happens when OpenD restarts after repeated failed logins or Moomoo flags the IP.
Telnet into OpenD and complete verification via SMS:

```bash
ssh $VPS_HOST
telnet 127.0.0.1 22222
```

In the telnet session:
```
relogin
```

Moomoo sends an SMS to your phone. Enter the code:
```
input_phone_verify_code -code=XXXXXX
```

You should see `Login successful` with your account quota. Paper runner reconnects automatically within 60s.

**If phone verify says "not available during current period"** — try `req_pic_verify_code` instead.
It downloads a CAPTCHA image to `/home/ubuntu/.com.moomoo.OpenD/*/PicVerifyCode.png`.
Copy it locally: `scp $VPS_HOST:/home/ubuntu/.com.moomoo.OpenD/*/PicVerifyCode.png ~/Desktop/captcha.png`
Then: `input_pic_verify_code -code=XXXXXX`

---

## VPS — Daily Operations

```bash
ssh $VPS_HOST

# Check status
systemctl --user status moomoo-opend.service moomoo-paper.service

# Watch live logs
journalctl --user -u moomoo-paper.service -f

# Check today's JSONL
tail -f ~/moomoo/logs/paper_US_IWM_$(date +%Y-%m-%d).jsonl

# Deploy code update from GitHub
cd ~/moomoo && ./deploy.sh

# Restart services
systemctl --user restart moomoo-opend.service
systemctl --user restart moomoo-paper.service

# Kill switch
touch ~/moomoo/STOP_TRADING.txt    # pause trading
rm ~/moomoo/STOP_TRADING.txt       # resume trading
```

---

## VPS — Sync Logs to Local

Pull today's logs from VPS to local for analysis:
```bash
rsync -av $VPS_HOST:~/moomoo/logs/ /home/logan/projects/moomoo/logs/
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
# Edit .env: STRATEGY_MODE=strict
systemctl --user restart moomoo-paper.service
# Sync to VPS if needed
scp .env $VPS_HOST:~/moomoo/.env && ssh $VPS_HOST 'systemctl --user restart moomoo-paper.service'
```

---

## File Locations

| File | Local | VPS |
|------|-------|-----|
| Code | `~/projects/moomoo/` | `~/moomoo/` |
| Config | `~/projects/moomoo/.env` | `~/moomoo/.env` |
| OpenD binary | `~/apps/moomoo-opend/` (AppImage) | `~/opend/` (headless) |
| OpenD config | n/a (GUI) | `~/opend/OpenD.xml` |
| Logs (JSONL) | `~/projects/moomoo/logs/` | `~/moomoo/logs/` |
| systemd services | `~/.config/systemd/user/` | `~/.config/systemd/user/` |
