# Route 3 — Real Money

**Status:** Parked  
**Priority:** Low (user preference — lower risk first)

## The Idea

Switch `TRD_ENV=REAL` and `LIVE_TRADING_ENABLED=true` on a small funded account
(even $500). The mechanics already work — the paper runner is production-quality.

## Why It's Parked

User noted preference for the lower-risk options (Routes 1 and 2) first. Real money
adds execution risk without adding research value until the paper data is more mature.

## When to Revisit

Consider this when:
- Routes 1 and 2 have been explored (new signals validated OOS in paper)
- bb_kdj or ORB have 90+ live paper trades (evaluation_criteria.md gates met)
- User has a small funded Moomoo account ready (even $500 account is fine — the
  position sizer caps each trade by MAX_POSITION_DOLLARS and MAX_DAILY_LOSS)

## What Would Need to Change

1. Moomoo account funded (real brokerage account, not paper simulate)
2. `.env`: `TRD_ENV=REAL`, `LIVE_TRADING_ENABLED=true`, `LIVE_CONFIRMATION=true`
3. Review `MAX_POSITION_DOLLARS` (currently 900 — might want to start at 200)
4. Review `MAX_DAILY_LOSS` (currently 20 — appropriate for small account)
5. Confirm `TRADE_PASSWORD_MD5` matches the funded account's trade password
6. Read `docs/ARCHITECTURE.md` kill switches section before flipping

The code path for real orders is identical to simulate — only the `TRD_ENV` env var
and the `LIVE_TRADING_ENABLED` guard separate them.

## Safety Notes (mandatory, not optional)

- Never set `LIVE_TRADING_ENABLED=true` without a corresponding funded account ready
- Always test with `LIVE_CONFIRMATION=true` the first week (manual order approval in Moomoo UI)
- Keep `STOP_TRADING.txt` kill switch in reach — touch this file to pause the runner
  without stopping the process
- Never run ORB shorts (`ORB_SHORT_SYMBOLS`) on a real account without re-validating
  paper performance first
- Monitor the first 5 live sessions manually (the logs stream in real time via `dashboard.py`)
