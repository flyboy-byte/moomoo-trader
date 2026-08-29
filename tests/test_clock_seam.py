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

# Keyed on (file, exact source line), NOT (file, line number). Line numbers were the
# original key and made this test break on any unrelated edit above an allowlisted
# call — an edit to the dashboard's scoreboard on 2026-08-29 shifted one entry by 16
# lines and failed the suite with a "violation" that was nothing of the sort. A
# content key survives insertions and deletions, and still fails when someone writes
# a genuinely new raw-clock call, which is the behaviour actually wanted.
ALLOWLIST = {
    # Fetch-window padding only — an off-by-one day shifts the buffer size,
    # never compared against ET-keyed state.
    ("mm/data.py",
     'end = datetime.now().strftime("%Y-%m-%d")'),
    ("mm/data.py",
     'start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")'),
    # Research-archive filename, "when fetched", not trading-day-keyed.
    ("mm/data.py",
     'date_str = datetime.now().strftime("%Y-%m-%d")'),
    ("scripts/fetch_daily_archive.py",
     'start = (datetime.now() - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")'),
    ("scripts/fetch_daily_archive.py",
     'end = datetime.now().strftime("%Y-%m-%d")'),
    ("scripts/fetch_vix_morning.py",
     'end = datetime.now().strftime("%Y-%m-%d")'),
    ("scripts/fetch_vix_morning.py",
     'start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")'),
    # Display-only — rendered once, never persisted/compared/sorted.
    ("scripts/dashboard.py",
     'updated_at=datetime.now(),'),
    ("scripts/web_dashboard.py",
     'now_str = datetime.now().strftime("%H:%M:%S")'),
    # Docstring prose, not a call.
    ("mm/replay.py",
     "Wall-clock is simulated: the runner sees datetime.now() as the replayed bar's"),
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
                if PATTERN.search(line) and (rel, line.strip()) not in ALLOWLIST:
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


def test_allowlist_has_no_stale_entries():
    """A content-keyed allowlist can rot the other way: an entry whose source line
    was deleted or rewritten silently stops protecting anything. Fail loudly so the
    entry gets removed rather than lingering as false reassurance."""
    stale = []
    for rel, text in ALLOWLIST:
        path = REPO_ROOT / rel
        if not path.exists():
            stale.append((rel, text, "file missing"))
            continue
        if text not in path.read_text():
            stale.append((rel, text, "line no longer present"))
    assert not stale, (
        "ALLOWLIST entries no longer match any source line — delete them:\n"
        + "\n".join(f"  {r}: {t!r} ({why})" for r, t, why in stale)
    )
