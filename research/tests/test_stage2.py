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
