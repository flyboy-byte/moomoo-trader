#!/usr/bin/env bash
set -euo pipefail

# Start OpenD if not already running
if systemctl --user is-active --quiet moomoo-opend.service; then
    echo "OpenD already running."
else
    echo "Starting OpenD..."
    systemctl --user start moomoo-opend.service
fi

# Wait for OpenD port to be ready (up to 20s)
echo "Waiting for OpenD at 127.0.0.1:11111..."
for i in $(seq 1 10); do
    if nc -z 127.0.0.1 11111 2>/dev/null; then
        echo "OpenD is up."
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "ERROR: OpenD port not available after 20s. Check: journalctl --user -u moomoo-opend.service"
        exit 1
    fi
    sleep 2
done

# Warn if MAX_POSITION_DOLLARS is too low to trade
MAX_POS=$(grep -E '^MAX_POSITION_DOLLARS=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
if [ -n "$MAX_POS" ] && awk "BEGIN{exit !($MAX_POS < 200)}"; then
    echo ""
    echo "WARNING: MAX_POSITION_DOLLARS=$MAX_POS is too low to buy any share of SPY/QQQ/IWM."
    echo "         Edit .env and raise it (IWM ~\$220, SPY ~\$560) before trades will fire."
    echo ""
fi

# Remove stale kill switch if present
if [ -f STOP_TRADING.txt ]; then
    echo "WARNING: STOP_TRADING.txt exists — removing it so trading is allowed."
    rm STOP_TRADING.txt
fi

# Start paper runner
if systemctl --user is-active --quiet moomoo-paper.service; then
    echo "Paper runner already running."
else
    echo "Starting paper runner..."
    systemctl --user start moomoo-paper.service
fi

echo ""
echo "=== Status ==="
systemctl --user status moomoo-opend.service --no-pager -l | head -6
echo ""
systemctl --user status moomoo-paper.service --no-pager -l | head -6
echo ""
echo "Logs:      journalctl --user -u moomoo-paper.service -f"
echo "Dashboard: python scripts/dashboard.py"
echo "Pause:     touch STOP_TRADING.txt"
