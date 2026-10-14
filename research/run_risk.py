"""Phase 3: loss probabilities for a £100 account and statistical power.

Loss probabilities come from a stationary block bootstrap (mean block 12
months, 10,000 paths) of historical monthly returns. This keeps volatility
clustering and crash sequences but assumes the future resembles the sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french
from dataset import build, factor_etfs
from engine import run
from strategies import bench, gem, trend_sma

OUT = DATA.parent / "output"
rng = np.random.default_rng(11)
R = build()

kf = french("F-F_Research_Data_Factors")
dec = french("10_Portfolios_Prior_12_2")
E = factor_etfs()
E = E[(E.index >= "2014-11-30") & (E.index <= "2026-09-30")].dropna()

series = {
    "WORLD b&h (GBP, 1992-2026)": run("w", R, bench("WORLD"), start="1992-01-31").returns,
    "GEM L=12 (GBP, 1992-2026)": run("g", R, gem(12, "US", "INTL", "BOND"), start="1992-01-31").returns,
    "SMA10 trend (GBP, 1992-2026)": run("s", R, trend_sma(10, "WORLD", "BOND"), start="1992-01-31").returns,
    "50/50 WORLD+MOM ETF (GBP, 2014-2026)": 0.5 * E["WORLD_ETF"] + 0.5 * E["MOM"] - 0.0015 / 12,  # FX fee proxy on IWMO
    "US market (USD, 1927-2026)": (kf["Mkt-RF"] + kf["RF"]).loc["1927":],
    "US top momentum decile (USD, 1927-2026)": dec["Hi PRIOR"].loc["1927":],
}
H = {"1y": 12, "3y": 36, "5y": 60, "10y": 120}
rows = []
for name, r in series.items():
    x = r.dropna().values
    n = len(x)
    for hl, h in H.items():
        ends, mdds = np.empty(10000), np.empty(10000)
        for k in range(10000):
            # draw a path of length h from the sample using circular blocks
            start = rng.integers(n)
            path = np.empty(h)
            j = start
            for i in range(h):
                if i > 0 and rng.random() < 1 / 12:
                    j = rng.integers(n)
                path[i] = x[j % n]
                j += 1
            eq = 100 * np.cumprod(1 + path)
            ends[k] = eq[-1]
            mdds[k] = (eq / np.maximum.accumulate(np.r_[100, eq])[1:] - 1).min()
        rows.append({"series": name, "horizon": hl, "median £": np.median(ends), "5th pct £": np.percentile(ends, 5),
                     "P(end<£100)": (ends < 100).mean(), "P(end<£80)": (ends < 80).mean(), "P(end<£50)": (ends < 50).mean(),
                     "P(drawdown>30% at some point)": (mdds < -0.30).mean(), "P(drawdown>50%)": (mdds < -0.50).mean()})
T = pd.DataFrame(rows)
T.to_csv(OUT / "loss_probabilities.csv", index=False)
pd.set_option("display.width", 250)
for name in series:
    print(name)
    sub = T[T.series == name].drop(columns="series")
    print(sub.to_string(index=False, formatters={"median £": "{:.0f}".format, "5th pct £": "{:.0f}".format,
                                                 **{c: "{:.1%}".format for c in sub.columns if c.startswith("P(")}}))

# ---- power: how long to tell a real edge from luck?
ex = (E["MOM"] - E["WORLD_ETF"])
te = ex.std() * np.sqrt(12)
for edge in (0.01, 0.02, 0.03):
    yrs = (2 * te / edge) ** 2
    print(f"\nEdge {edge:.0%}/yr with tracking error {te:.1%}: ~{yrs:.0f} years of data for t=2" if edge == 0.01 else
          f"Edge {edge:.0%}/yr with tracking error {te:.1%}: ~{yrs:.0f} years of data for t=2")
