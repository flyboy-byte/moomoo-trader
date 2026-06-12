#!/usr/bin/env bash
# One-command session health check.
#
# Usage:
#   ./scripts/verify.sh                  # checks today's session
#   ./scripts/verify.sh --date 2026-06-04
#   ./scripts/verify.sh --no-sync        # skip VPS log sync (use local logs)
#
# Runs: pytest → sync logs → diagnose_logs → compare_paper_vs_backtest (all symbols)
# Exit code: 0 if all checks pass, 1 if any fail.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SESSION_DATE=$(date +%Y-%m-%d)
SKIP_SYNC=false

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --date) SESSION_DATE="$2"; shift 2 ;;
        --no-sync) SKIP_SYNC=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

source .venv/bin/activate

PASS="✓"
FAIL="✗"
OVERALL=0

section() { echo; echo "══════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════"; }

# ── 1. Unit tests ──────────────────────────────────────────────────────────
section "1. UNIT TESTS"
if python -m pytest tests/ -q --tb=short 2>&1; then
    echo "$PASS  All tests passed"
else
    echo "$FAIL  Tests FAILED"
    OVERALL=1
fi

# ── 2. Sync logs from VPS ──────────────────────────────────────────────────
if [ "$SKIP_SYNC" = false ]; then
    section "2. SYNC LOGS"
    if ./sync_logs.sh 2>&1 | tail -3; then
        echo "$PASS  Logs synced"
    else
        echo "$FAIL  Sync failed (continuing with local logs)"
    fi
else
    section "2. SYNC LOGS (skipped)"
fi

# ── 3. Session diagnostics ─────────────────────────────────────────────────
section "3. SESSION DIAGNOSTICS  ($SESSION_DATE)"
DIAG_FILES=$(ls logs/paper_US_*_${SESSION_DATE}.jsonl 2>/dev/null | wc -l)
if [ "$DIAG_FILES" -eq 0 ]; then
    echo "  No log files found for $SESSION_DATE — market may not have opened yet."
else
    python scripts/diagnose_logs.py --date "$SESSION_DATE" 2>&1
fi

# ── 4. Signal engine agreement ─────────────────────────────────────────────
section "4. SIGNAL ENGINE AGREEMENT  ($SESSION_DATE)"
COMPARE_PASS=0
COMPARE_FAIL=0
for f in logs/paper_US_*_${SESSION_DATE}.jsonl; do
    [ -f "$f" ] || continue
    SYM=$(basename "$f" | sed "s/paper_//;s/_${SESSION_DATE}\.jsonl//;s/_/./")
    echo -n "  $SYM  "
    if python scripts/compare_paper_vs_backtest.py "$f" 2>/dev/null \
        | grep -E "✓|✗" | head -1; then
        COMPARE_PASS=$((COMPARE_PASS + 1))
    else
        echo "$FAIL  compare failed"
        COMPARE_FAIL=$((COMPARE_FAIL + 1))
        OVERALL=1
    fi
done
if [ "$COMPARE_FAIL" -gt 0 ]; then
    echo "$FAIL  $COMPARE_FAIL symbol(s) failed signal agreement check"
else
    echo "$PASS  $COMPARE_PASS symbol(s) passed signal agreement check"
fi

# ── 5. Replay-vs-live decision diff ────────────────────────────────────────
section "5. REPLAY-VS-LIVE DIFF  ($SESSION_DATE)"
if [ "$DIAG_FILES" -eq 0 ]; then
    echo "  No live logs for $SESSION_DATE — skipping"
else
    DIFF_OUT=$(python scripts/replay_vs_live.py --date "$SESSION_DATE" 2>/dev/null) \
        && DIFF_RC=0 || DIFF_RC=$?
    echo "$DIFF_OUT" | grep -E "✓|✗|SKIP|variance|first entry|exit decisions" || true
    if [ "$DIFF_RC" -ne 0 ]; then
        echo "$FAIL  live runner and replay disagree — investigate before next session"
        OVERALL=1
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────────
section "SUMMARY"
if [ "$OVERALL" -eq 0 ]; then
    echo "  $PASS  All checks passed  ($SESSION_DATE)"
else
    echo "  $FAIL  One or more checks FAILED  ($SESSION_DATE)"
fi
echo

exit $OVERALL
