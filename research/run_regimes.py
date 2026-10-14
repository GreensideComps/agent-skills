"""Regime breakdown for selected strategies + 100-year US trend-following check."""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french
from dataset import build
from engine import compare, metrics, run
from strategies import gem, rotation, static, bench, trend_abs, trend_sma, inverse_vol

OUT = DATA.parent / "output"
R = build()
cash = R["CASH"]
S = {
    "WORLD b&h": bench("WORLD"),
    "60/40": static({"WORLD": 0.6, "BOND": 0.4}),
    "GEM L=12": gem(12, "US", "INTL", "BOND"),
    "SMA L=10": trend_sma(10, "WORLD", "BOND"),
    "TSMOM L=8": trend_abs(8, "WORLD", "BOND"),
    "ROT K=1 L=12": rotation(1, 12),
    "InvVol L=12": inverse_vol(("WORLD", "BOND", "GOLD"), 12),
}
res = {k: run(k, R, f, start="1992-01-31") for k, f in S.items()}
regimes = {
    "1992-99 bull": ("1992-01", "1999-12"), "2000-02 dot-com bust": ("2000-01", "2003-03"),
    "2003-07 recovery": ("2003-04", "2007-10"), "2007-09 GFC": ("2007-11", "2009-02"),
    "2009-19 long bull": ("2009-03", "2019-12"), "2020 Covid": ("2020-01", "2020-12"),
    "2022 rate shock": ("2022-01", "2022-12"), "2023-26 AI bull": ("2023-01", "2026-09"),
}
rows = []
for reg, (a, b) in regimes.items():
    row = {"regime": reg}
    for k, r in res.items():
        x = r.returns[(r.returns.index >= a) & (r.returns.index <= pd.Timestamp(b) + pd.offsets.MonthEnd(0))]
        row[k] = (1 + x).prod() ** (12 / len(x)) - 1
    rows.append(row)
T = pd.DataFrame(rows).set_index("regime")
T.to_csv(OUT / "regimes_annualised.csv")
print("Annualised GBP return by regime:")
print(T.map(lambda v: f"{v:+.1%}").to_string())

# cost stress for GEM in OOS
for mult in (1, 3, 5):
    r = run("GEM", R, S["GEM L=12"], start="2011-01-31", cost_mult=mult)
    m = metrics(r.returns, cash, r.turnover)
    print(f"GEM L=12 OOS cost x{mult}: CAGR {m['CAGR']:.2%} Sharpe {m['Sharpe']:.2f}")

# ---- 100-year US check (USD, gross index, survivorship-free CRSP via Ken French)
kf = french("F-F_Research_Data_Factors")
us = kf["Mkt-RF"] + kf["RF"]
D = pd.DataFrame({"US": us, "CASH": kf["RF"]})
print("\nUS 1927-2026 (USD, CRSP value-weighted market vs T-bills, 0.1% per switch):")
cost = {"US": 0.001, "CASH": 0.0}
rows = []
for name, fn in {"US b&h": bench("US"), "SMA L=10": trend_sma(10, "US", "CASH"), "TSMOM L=12": trend_abs(12, "US", "CASH")}.items():
    r = run(name, D, fn, start="1928-01-31", costs=cost)
    for per, (a, b) in {"1928-1949": ("1928", "1949"), "1950-1989": ("1950", "1989"), "1990-2010": ("1990", "2010"), "2011-2026": ("2011", "2026"), "ALL": ("1928", "2026")}.items():
        x = r.returns[(r.returns.index >= a) & (r.returns.index <= f"{b}-12-31")]
        m = metrics(x, D["CASH"], r.turnover)
        rows.append({"strategy": name, "period": per, "CAGR": m["CAGR"], "Sharpe": m["Sharpe"], "maxDD": m["maxDD"], "switches_pa": m["turnover_pa"]})
    if name != "US b&h":
        b = run("b", D, bench("US"), start="1928-01-31", costs=cost).returns
        c = compare(r.returns, b.reindex(r.returns.index), D["CASH"], n_boot=3000)
        print(f"  {name} vs b&h, 1928-2026: dSharpe {c['dSharpe']:+.2f} (p={c['p_Sharpe']:.3f}), dCAGR {c['dCAGR']:+.2%} (p={c['p_CAGR']:.3f})")
U = pd.DataFrame(rows)
U.to_csv(OUT / "us_century_trend.csv", index=False)
print(U.pivot(index="period", columns="strategy", values=["CAGR", "Sharpe", "maxDD"]).map(lambda v: f"{v:.2f}").to_string())
