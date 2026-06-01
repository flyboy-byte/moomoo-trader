#!/usr/bin/env bash
set -euo pipefail

# Stop the paper runner (OpenD stays running)
if systemctl --user is-active --quiet moomoo-paper.service; then
    echo "Stopping paper runner..."
    systemctl --user stop moomoo-paper.service
    echo "Paper runner stopped."
else
    echo "Paper runner is not running."
fi

# Clean up kill switch if it was left set
if [ -f STOP_TRADING.txt ]; then
    rm STOP_TRADING.txt
    echo "Removed STOP_TRADING.txt."
fi

echo ""
systemctl --user status moomoo-paper.service --no-pager -l | head -6
echo ""
echo "OpenD is still running. To stop it: systemctl --user stop moomoo-opend.service"
