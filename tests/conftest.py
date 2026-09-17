"""Suite-wide guard: no test may create or modify anything in the real logs/.

Twice now a test has leaked into the never-pruned research data: fixture bars in
the IWM archive (2026-08-24) and replay JSONL in logs/ (found 2026-09-17). Both
hid for weeks. This makes the next one fail the run instead.
"""
from pathlib import Path

import pytest

LOGS = Path(__file__).resolve().parent.parent / "logs"
WATCHED = ("paper_*", "*_combined.csv", "*.jsonl")


def _snapshot() -> dict[str, float]:
    if not LOGS.exists():
        return {}
    files = {p for pattern in WATCHED for p in LOGS.glob(pattern)}
    return {p.name: p.stat().st_mtime for p in files if p.is_file()}


@pytest.fixture(scope="session", autouse=True)
def real_logs_untouched():
    before = _snapshot()
    yield
    after = _snapshot()
    # The live runner does not run locally, so nothing should change here at all.
    changed = sorted(n for n in after if before.get(n) != after[n])
    assert not changed, f"tests wrote into the real logs/ directory: {changed[:10]}"
