import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regime  # noqa: E402


def _daily(n_days=1700, seed=0):
    idx = pd.bdate_range("2009-01-01", periods=n_days)
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"Mkt-RF": rng.normal(0.0003, 0.01, n_days), "RF": 0.00005}, index=idx)


def test_regimes_use_only_prior_month():
    d = _daily()
    base = regime.regimes(d)
    changed = d.copy()
    last = changed.index[changed.index.to_period("M") == changed.index[-1].to_period("M")]
    changed.loc[last, "Mkt-RF"] = 0.5  # a huge move inside the final month
    after = regime.regimes(changed)
    # the final decision month's flags must not see its own month
    pd.testing.assert_series_equal(base["R1"].iloc[:-1], after["R1"].iloc[:-1])
    assert base["R1"].iloc[-1] == after["R1"].iloc[-1]
    assert base["R2"].iloc[-1] == after["R2"].iloc[-1]


def test_r3_is_return_month_nov_to_apr():
    r = regime.regimes(_daily())
    oct_end = r.index[r.index.month == 10][0]
    apr_end = r.index[r.index.month == 4][0]
    assert bool(r.loc[oct_end, "R3"]) and not bool(r.loc[apr_end, "R3"])


def test_conditional_costs_entry_and_exit():
    months = pd.date_range("2015-01-31", periods=4, freq="ME")
    s = pd.DataFrame({"month": months, "q5_minus_univ": 0.01, "q5_turnover": 0.2})
    on = pd.Series([False, True, True, False], index=months)
    x = regime.conditional(s, on)
    c = regime.COST
    assert x.iloc[0] == 0 and x.iloc[3] == 0
    assert np.isclose(x.iloc[1], 0.01 - 4 * c * 1.0)  # entry: full turnover
    assert np.isclose(x.iloc[2], 0.01 - 4 * c * (0.2 + 1.0))  # carry turnover plus exit


def test_holm_step_down():
    ok = regime.holm({"a": 0.001, "b": 0.02, "c": 0.04})
    assert ok == {"a": True, "b": True, "c": True}
    ok = regime.holm({"a": 0.001, "b": 0.04, "c": 0.01})
    assert ok == {"a": True, "c": True, "b": True} or ok["b"] is True
    ok = regime.holm({"a": 0.03, "b": 0.04})
    assert ok == {"a": False, "b": False}


def test_b_flags():
    cal = pd.bdate_range("2019-12-20", "2020-01-10").drop(pd.Timestamp("2019-12-25")).drop(pd.Timestamp("2020-01-01"))
    f = regime.b_flags(cal)
    assert bool(f["B3"].loc["2019-12-24"]) and bool(f["B3"].loc["2019-12-31"])
    assert not bool(f["B3"].loc["2019-12-27"])  # only a weekend follows
    assert bool(f["B2"].loc["2019-12-31"]) and bool(f["B2"].loc["2020-01-06"])
    assert not bool(f["B2"].loc["2020-01-07"])


def test_daily_switch_out_of_market_earns_cash_minus_market():
    d = _daily(60)
    flag = pd.Series(False, index=d.index)
    x = regime.daily_switch(d, flag)
    expect = (d["RF"] - (d["Mkt-RF"] + d["RF"])).resample("ME").sum()
    pd.testing.assert_series_equal(x, expect, check_names=False)
