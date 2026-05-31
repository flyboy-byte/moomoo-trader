#!/usr/bin/env python3
"""Check that OpenD is reachable and quote data is working.

Usage:
    python scripts/health_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.health import run_health_check

if not run_health_check():
    sys.exit(1)
