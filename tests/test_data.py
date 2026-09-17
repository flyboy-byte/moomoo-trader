import pytest
import pandas as pd

from mm.data import update_combined_csv
from mm import config as _config


def _df(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "time_key": [r[0] for r in rows],
        "open": [r[1] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[1] for r in rows],
        "close": [r[1] for r in rows],
        "volume": [100 for _ in rows],
    })


def test_update_combined_csv_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    df = _df([("2026-06-16 09:35:00", 100.0), ("2026-06-16 09:40:00", 101.0)])
    path = update_combined_csv(df, "US.IWM", "K_5M")
    assert path.exists()
    out = pd.read_csv(path)
    assert len(out) == 2


def test_update_combined_csv_appends_new_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    df1 = _df([("2026-06-16 09:35:00", 100.0)])
    df2 = _df([("2026-06-16 09:40:00", 101.0)])
    update_combined_csv(df1, "US.IWM", "K_5M")
    path = update_combined_csv(df2, "US.IWM", "K_5M")
    out = pd.read_csv(path)
    assert len(out) == 2
    assert sorted(out["time_key"].tolist()) == ["2026-06-16 09:35:00", "2026-06-16 09:40:00"]


def test_update_combined_csv_dedups_keeps_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    df1 = _df([("2026-06-16 09:35:00", 100.0)])
    df2 = _df([("2026-06-16 09:35:00", 999.0)])  # revised bar, same time_key
    update_combined_csv(df1, "US.IWM", "K_5M")
    path = update_combined_csv(df2, "US.IWM", "K_5M")
    out = pd.read_csv(path)
    assert len(out) == 1
    assert out.iloc[0]["close"] == 999.0


def test_update_combined_csv_extended_time_separate_file(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    df = _df([("2026-06-16 04:05:00", 100.0)])
    rth_path = update_combined_csv(df, "US.IWM", "K_5M", extended_time=False)
    ext_path = update_combined_csv(df, "US.IWM", "K_5M", extended_time=True)
    assert rth_path != ext_path
    assert "_EXT_" in ext_path.name
    assert "_EXT_" not in rth_path.name


def test_update_combined_csv_quarantines_corrupt_archive_instead_of_wiping(tmp_path, monkeypatch):
    """Bug fix 2026-08-25: an unreadable existing archive must be quarantined
    and the call must raise, never silently replaced with just the new fetch
    (that used to erase years of never-pruned history)."""
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    path = tmp_path / "US_IWM_K_5M_combined.csv"
    path.write_text("not,a,valid,csv\x00\x01garbage")

    df = _df([("2026-06-16 09:35:00", 100.0)])
    with pytest.raises(Exception):
        update_combined_csv(df, "US.IWM", "K_5M")

    # Original path must not silently contain just the new fetch.
    assert not path.exists() or path.read_text().startswith("not,a,valid,csv")
    quarantined = list(tmp_path.glob("US_IWM_K_5M_combined.corrupt-*.csv"))
    assert len(quarantined) == 1
    assert "garbage" in quarantined[0].read_text()


# ---------------------------------------------------------------------------
# Price-basis changes (QFQ re-scaling after a dividend/split) — PLAN.md Step 7
# ---------------------------------------------------------------------------

def _day_bars(date: str, base: float, n: int = 78) -> list[tuple[str, float]]:
    ts = pd.date_range(f"{date} 09:35", periods=n, freq="5min")
    return [(t.strftime("%Y-%m-%d %H:%M:%S"), base + i * 0.01) for i, t in enumerate(ts)]


def _scaled(rows, f):
    return [(t, p * f) for t, p in rows]


def test_rebases_history_when_pull_is_on_a_new_basis(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    d1, d2, d3 = _day_bars("2026-06-01", 100), _day_bars("2026-06-02", 101), _day_bars("2026-06-03", 102)
    update_combined_csv(_df(d1 + d2), "US.SPY", "K_5M")
    # a dividend went ex: the new pull re-scales d2 and adds d3
    path = update_combined_csv(_df(_scaled(d2, 0.997) + d3), "US.SPY", "K_5M")
    out = pd.read_csv(path).set_index("time_key")["close"]
    for t, p in d1:  # untouched-by-pull history moved onto the new basis
        assert out[t] == pytest.approx(p * 0.997)
    for t, p in d2:
        assert out[t] == pytest.approx(p * 0.997)
    ratios = (out.iloc[1:].values / out.iloc[:-1].values)
    assert abs(ratios - 1).max() < 0.01  # no seam anywhere
    assert len(list(tmp_path.glob("US_SPY_K_5M_combined.pre-rebase-*.csv"))) == 1


def test_same_basis_pull_merges_without_rebase(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    d1, d2 = _day_bars("2026-06-01", 100), _day_bars("2026-06-02", 101)
    update_combined_csv(_df(d1 + d2), "US.SPY", "K_5M")
    path = update_combined_csv(_df(d2 + _day_bars("2026-06-03", 102)), "US.SPY", "K_5M")
    out = pd.read_csv(path).set_index("time_key")["close"]
    assert out[d1[0][0]] == d1[0][1]
    assert not list(tmp_path.glob("*.pre-rebase-*"))


def test_inconsistent_overlap_is_refused_and_archive_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    d1 = _day_bars("2026-06-01", 100)
    path = update_combined_csv(_df(d1), "US.SPY", "K_5M")
    before = path.read_text()
    bad = [(t, p * (1.0 if i % 2 else 1.01)) for i, (t, p) in enumerate(d1)]
    with pytest.raises(Exception, match="not constant"):
        update_combined_csv(_df(bad), "US.SPY", "K_5M")
    assert path.read_text() == before
    assert len(list(tmp_path.glob("US_SPY_K_5M_combined.basis-mismatch-*.csv"))) == 1


def test_non_overlapping_pull_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    path = update_combined_csv(_df(_day_bars("2026-06-01", 100)), "US.SPY", "K_5M")
    before = path.read_text()
    with pytest.raises(Exception, match="does not overlap"):
        update_combined_csv(_df(_day_bars("2026-06-10", 105)), "US.SPY", "K_5M")
    assert path.read_text() == before
