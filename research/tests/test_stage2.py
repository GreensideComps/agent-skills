"""Stage 2 helpers: exact lags, deflated Sharpe behaves, SIC groups."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage2  # noqa: E402


def test_lag_requires_the_exact_month():
    df = pd.DataFrame({"cik": [1, 1, 1, 2], "month": pd.to_datetime(["2020-01-31", "2020-02-29", "2020-04-30", "2020-02-29"]),
                       "x": [1.0, 2.0, 4.0, 9.0]})
    df["p"] = df["month"].dt.to_period("M")
    lagged = stage2.lag(df, "x", 1)
    assert np.isnan(lagged.iloc[0]) and lagged.iloc[1] == 1.0
    assert np.isnan(lagged.iloc[2]) and np.isnan(lagged.iloc[3])  # a gap, and another company


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(0.01, 0.03, 96))
    st = stage2.sharpe_stats(x)
    one = stage2.deflated_sharpe(st, [st["sr"]])
    many = stage2.deflated_sharpe(st, list(rng.normal(0, 0.15, 50)) + [st["sr"]])
    assert one > many and 0 <= many <= 1


def test_sic_groups():
    assert stage2.sic_group("3674") == "electronics_semis" and stage2.sic_group("7372") == "software_it"
    assert stage2.sic_group("6021") == "finance" and stage2.sic_group("") == "unknown"
    assert stage2.sic_group("3711") == "other_manufacturing"


def test_insider_window_counts_distinct_people_by_filing_month():
    df = pd.DataFrame({"cik": [7, 7, 7], "month": pd.to_datetime(["2020-01-31", "2020-06-30", "2020-07-31"]),
                       "mcap": [1e9, 1e9, 1e9]})
    df["p"] = df["month"].dt.to_period("M")
    trades = pd.DataFrame({"issuer_cik": [7, 7, 7, 7], "filed": ["2020-01-10", "2020-01-20", "2020-01-25", "2020-02-01"],
                           "owner_cik": [1, 1, 2, 3], "code": ["P", "P", "S", "S"], "shares": [100, 100, 5, 5],
                           "price": [10.0, 10.0, 9.0, 9.0]})
    f = stage2.insider_features(df, trades)
    assert f["s7a_net_buyers"].iloc[0] == 0.0  # one buyer (counted once), one seller filed by January
    assert f["s7b_buy_value"].iloc[0] == 2000 / 1e9
    assert f["s7a_net_buyers"].iloc[1] == -1 / 3  # June: buyer 1, sellers 2 and 3 within 6 filing months
    assert f["s7a_net_buyers"].iloc[2] == -1 and f["s7b_buy_value"].iloc[2] == 0  # July: January has aged out


def test_residual_momentum_recovers_a_planted_drift():
    rng = np.random.default_rng(3)
    months = pd.date_range("2010-01-31", periods=60, freq="ME")
    ff = pd.DataFrame({"Mkt-RF": rng.normal(0.01, 0.04, 60), "SMB": rng.normal(0, 0.02, 60),
                       "HML": rng.normal(0, 0.02, 60), "RF": 0.001}, index=months)
    rows = []
    for c, drift in ((1, 0.0), (2, 0.02)):
        px = 100.0
        for i, m in enumerate(months):
            ret = 0.001 + ff["Mkt-RF"].iloc[i] + (drift if i >= 40 else 0) + rng.normal(0, 0.01)
            px *= 1 + ret
            rows.append({"cik": c, "month": m, "adjclose": px})
    df = pd.DataFrame(rows)
    df["p"] = df["month"].dt.to_period("M")
    s = stage2.residual_momentum(df, ff)
    last = df["month"] == months[-1]
    assert s[last & (df["cik"] == 2)].iloc[0] > s[last & (df["cik"] == 1)].iloc[0]
