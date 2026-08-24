"""Static guard against the recurring clock-seam-violation bug class.

mm/clock.py exists specifically so day-boundary/timestamp logic is keyed to
the ET trading day (now_et()/today()), not server-local wall-clock time.
Bypassing it with raw datetime.now()/date.today() has caused 4 real bugs so
far: clock.today() itself (2026-06-17), PaperEventLog's filename/ts field
(2026-06-18), and follow-on regressions in web_dashboard.py/weekly_report.py/
diagnose_logs.py/analyze_trades.py the same day. This test greps the repo so
the 5th instance gets caught by `pytest` instead of by a fork audit weeks
later.

ALLOWLIST holds genuinely harmless call sites: pure fetch-window padding
(off-by-a-day doesn't change correctness, just buffer size) or display-only
strings never compared/sorted/bucketed against anything. Any new offender
must be fixed (use mm.clock) or added here with a one-line justification.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PATTERN = re.compile(r"\bdatetime\.now\(\)|\bdate\.today\(\)")

ALLOWLIST = {
    # Fetch-window padding only — an off-by-one day shifts the buffer size,
    # never compared against ET-keyed state.
    ("mm/data.py", 39),
    ("mm/data.py", 41),
    ("mm/data.py", 87),  # research-archive filename, "when fetched", not trading-day-keyed
    ("scripts/fetch_daily_archive.py", 42),
    ("scripts/fetch_daily_archive.py", 43),
    ("scripts/fetch_vix_morning.py", 48),
    ("scripts/fetch_vix_morning.py", 49),
    # Display-only — rendered once, never persisted/compared/sorted.
    ("scripts/dashboard.py", 228),
    ("scripts/web_dashboard.py", 1009),
    # Docstring prose, not a call.
    ("mm/replay.py", 13),
}

SCAN_DIRS = ["mm", "scripts"]
EXCLUDE_FILES = {"mm/clock.py"}


def _offenders() -> list[tuple[str, int, str]]:
    found = []
    for d in SCAN_DIRS:
        for path in sorted((REPO_ROOT / d).glob("*.py")):
            rel = f"{d}/{path.name}"
            if rel in EXCLUDE_FILES:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if PATTERN.search(line) and (rel, lineno) not in ALLOWLIST:
                    found.append((rel, lineno, line.strip()))
    return found


def test_no_unallowlisted_clock_seam_violations():
    offenders = _offenders()
    assert not offenders, (
        "Raw datetime.now()/date.today() found outside mm/clock.py — use "
        "clock.now_et()/clock.today() instead, or add to ALLOWLIST in this "
        "test with justification if genuinely harmless:\n" +
        "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_allowlist_entries_still_exist():
    """Catch stale allowlist entries (line moved/removed) — keeps the list honest."""
    for rel, lineno in ALLOWLIST:
        path = REPO_ROOT / rel
        assert path.exists(), f"Allowlisted file no longer exists: {rel}"
        lines = path.read_text().splitlines()
        assert lineno <= len(lines), f"Allowlisted line gone: {rel}:{lineno}"
        assert PATTERN.search(lines[lineno - 1]), (
            f"Allowlist entry {rel}:{lineno} no longer matches a clock call — "
            "remove it or update the line number"
        )
