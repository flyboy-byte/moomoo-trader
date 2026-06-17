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


def test_update_combined_csv_creates_file(tmp_path):
    _config.cfg.logs_dir = tmp_path
    df = _df([("2026-06-16 09:35:00", 100.0), ("2026-06-16 09:40:00", 101.0)])
    path = update_combined_csv(df, "US.IWM", "K_5M")
    assert path.exists()
    out = pd.read_csv(path)
    assert len(out) == 2


def test_update_combined_csv_appends_new_rows(tmp_path):
    _config.cfg.logs_dir = tmp_path
    df1 = _df([("2026-06-16 09:35:00", 100.0)])
    df2 = _df([("2026-06-16 09:40:00", 101.0)])
    update_combined_csv(df1, "US.IWM", "K_5M")
    path = update_combined_csv(df2, "US.IWM", "K_5M")
    out = pd.read_csv(path)
    assert len(out) == 2
    assert sorted(out["time_key"].tolist()) == ["2026-06-16 09:35:00", "2026-06-16 09:40:00"]


def test_update_combined_csv_dedups_keeps_latest(tmp_path):
    _config.cfg.logs_dir = tmp_path
    df1 = _df([("2026-06-16 09:35:00", 100.0)])
    df2 = _df([("2026-06-16 09:35:00", 999.0)])  # revised bar, same time_key
    update_combined_csv(df1, "US.IWM", "K_5M")
    path = update_combined_csv(df2, "US.IWM", "K_5M")
    out = pd.read_csv(path)
    assert len(out) == 1
    assert out.iloc[0]["close"] == 999.0


def test_update_combined_csv_extended_time_separate_file(tmp_path):
    _config.cfg.logs_dir = tmp_path
    df = _df([("2026-06-16 04:05:00", 100.0)])
    rth_path = update_combined_csv(df, "US.IWM", "K_5M", extended_time=False)
    ext_path = update_combined_csv(df, "US.IWM", "K_5M", extended_time=True)
    assert rth_path != ext_path
    assert "_EXT_" in ext_path.name
    assert "_EXT_" not in rth_path.name
