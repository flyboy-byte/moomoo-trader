"""Static guard for the module-ref-staleness bug class.

`tests/test_config_staleness.py` covers this behaviourally, but one hand-written
test per module — so a module nobody thought to add is simply never checked.
That is exactly how `mm/data.py` slipped through the 2026-06-18 fork audit and
went on to write test fixtures into the real research archive for two months
(see "Stale cfg in mm/data.py poisoned the live research archive" in
docs/strategy_graveyard.md).

This test greps instead, so the *next* module is covered the day it is written.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MM = REPO_ROOT / "mm"

# `from .config import cfg` / `from mm.config import cfg, validate_config` / etc.
PATTERN = re.compile(r"^\s*from\s+(?:\.|mm\.)config\s+import\s+(.+)$")

ALLOWLIST = {
    # mm/paper.py is the module the reload helpers reload (tests/test_vix_gate.py
    # reloads mm.config then mm.paper), so its binding is refreshed by
    # construction. Left on the import-time pattern deliberately: it is the live
    # paper runner, and rewriting its imports buys no behavioural change.
    # If a reload path ever stops reloading mm.paper, fix this properly.
    "paper.py",
}


def _offenders() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(MM.glob("*.py")):
        if path.name in ALLOWLIST or path.name == "config.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            m = PATTERN.match(line)
            if m and re.search(r"\bcfg\b", m.group(1)):
                found.append((f"mm/{path.name}", lineno, line.strip()))
    return found


def test_no_import_time_cfg_binding():
    offenders = _offenders()
    assert not offenders, (
        "`from .config import cfg` binds the Config instance at import time and goes "
        "stale the moment anything reassigns mm.config.cfg. Use `from . import config "
        "as _config` and re-fetch `cfg = _config.cfg` inside each function:\n" +
        "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_allowlist_entries_still_exist():
    """Keep the allowlist honest — a stale entry silently widens the hole."""
    for name in ALLOWLIST:
        path = MM / name
        assert path.exists(), f"Allowlisted module no longer exists: mm/{name}"
        assert any(
            PATTERN.match(line) and re.search(r"\bcfg\b", PATTERN.match(line).group(1))
            for line in path.read_text().splitlines()
        ), (
            f"mm/{name} is allowlisted but no longer uses the import-time pattern — "
            "remove it from ALLOWLIST"
        )
