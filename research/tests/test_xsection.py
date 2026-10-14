"""Cross-sectional harness: a planted signal is found, noise is not, costs are charged."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import xsection  # noqa: E402


def frame(n=200, months=60, seed=0, planted=0.02):
    rng = np.random.default_rng(seed)
    rows = []
    for mo in pd.date_range("2013-01-31", periods=months, freq="ME"):
        s = rng.normal(size=n)
        for i in range(n):
            rows.append({"cik": i, "month": mo, "close_raw": 50.0, "band": "large" if i % 2 else "mid",
                         "mcap": 20e9 if i % 2 else 5e9, "s": s[i],
                         "ret_next": planted * s[i] + rng.normal(scale=0.08)})
    return pd.DataFrame(rows)


def test_planted_signal_is_detected_and_noise_is_not():
    df = frame()
    good = xsection.evaluate(df, lambda g: g["s"], "planted", start="2013-01-31", end="2018-12-31", bands=("large",))
    b = good["bands"]["large"]
    assert b["months"] == 60 and b["mean_ic"] > 0.15 and b["ic_t_nw"] > 5
    assert b["q5_minus_univ_ann_net"] < b["q5_minus_univ_ann_gross"]  # costs charged
    rng = np.random.default_rng(1)
    noise = xsection.evaluate(df, lambda g: pd.Series(rng.normal(size=len(g)), index=g.index), "noise",
                              start="2013-01-31", end="2018-12-31", bands=("large",))
    assert abs(noise["bands"]["large"]["ic_t_nw"]) < 3


def test_window_and_min_price_respected():
    df = frame(months=24)
    df.loc[df["cik"] == 1, "close_raw"] = 0.5  # penny stock excluded
    out = xsection.evaluate(df, lambda g: g["s"], "x", start="2013-06-30", end="2013-12-31", bands=("large",))
    assert out["bands"]["large"]["months"] == 7
    assert out["bands"]["large"]["avg_names"] == 99


def test_newey_west_needs_enough_months():
    assert xsection.newey_west_t(pd.Series([0.1] * 5)) is None
