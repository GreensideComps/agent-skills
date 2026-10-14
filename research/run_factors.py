"""Systematic stock selection: are factor premia (momentum, value, quality,
low-vol) still there, and can a £100 account capture them via UCITS ETFs?"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_sources import DATA, french
from dataset import build, factor_etfs
from engine import compare, metrics

OUT = DATA.parent / "output"


def ann_t(x: pd.Series):
    x = x.dropna()
    return x.mean() * 12, x.mean() / x.std() * np.sqrt(len(x))


# A. Long-short factor premia (gross, academic, survivorship-free) by sub-period
us3 = french("F-F_Research_Data_Factors")
us5 = french("F-F_Research_Data_5_Factors_2x3")
mom = french("F-F_Momentum_Factor")["Mom"]
dev5 = french("Developed_5_Factors")
devm = french("Developed_Mom_Factor")["WML"]
F = {
    "US momentum (UMD)": mom, "US value (HML)": us3["HML"], "US profitability (RMW)": us5["RMW"],
    "Dev momentum (WML)": devm, "Dev value (HML)": dev5["HML"], "Dev profitability (RMW)": dev5["RMW"],
}
periods = {"1927-1989": ("1927", "1989"), "1990-2010": ("1990", "2010"), "2011-2026": ("2011", "2026")}
rows = []
for k, s in F.items():
    row = {"factor": k}
    for p, (a, b) in periods.items():
        x = s[(s.index >= a) & (s.index <= f"{b}-12-31")]
        if len(x) < 60:
            row[p] = ""
            continue
        m, t = ann_t(x)
        row[p] = f"{m:+.1%} (t={t:.1f})"
    rows.append(row)
A = pd.DataFrame(rows).set_index("factor")
print("A. Long-short factor premia, annualised mean, gross of costs (USD):")
print(A.to_string())
A.to_csv(OUT / "factor_premia_by_period.csv")

# B. Long-only US momentum: top decile (value-weighted) minus market
dec = french("10_Portfolios_Prior_12_2")
mkt = us3["Mkt-RF"] + us3["RF"]
ex = (dec["Hi PRIOR"] - mkt).dropna()
print("\nB. Long-only US top momentum decile minus market (gross, no trading costs):")
for p, (a, b) in periods.items():
    x = ex[(ex.index >= a) & (ex.index <= f"{b}-12-31")]
    m, t = ann_t(x)
    print(f"  {p}: {m:+.2%}/yr (t={t:.1f})")

# C. Tradeable UCITS factor ETFs on Trading 212 (GBP/GBX lines => no FX fee)
E = factor_etfs()
E = E[(E.index >= "2014-11-30") & (E.index <= "2026-09-30")].dropna()
cash = build()["CASH"]
print(f"\nC. MSCI World factor UCITS ETFs vs MSCI World (SWDA), {E.index[0]:%Y-%m}..{E.index[-1]:%Y-%m}, GBP, net of fund fees:")
rows = []
for k in ["WORLD_ETF", "MOM", "QUALITY", "VALUE", "MINVOL"]:
    m = metrics(E[k], cash)
    c = compare(E[k], E["WORLD_ETF"], cash, n_boot=3000) if k != "WORLD_ETF" else {}
    rows.append({"etf": k, "CAGR": m["CAGR"], "vol": m["vol"], "Sharpe": m["Sharpe"], "maxDD": m["maxDD"],
                 "dCAGR": c.get("dCAGR", np.nan), "p_CAGR": c.get("p_CAGR", np.nan),
                 "dSharpe": c.get("dSharpe", np.nan), "p_Sharpe": c.get("p_Sharpe", np.nan)})
C = pd.DataFrame(rows)
C.to_csv(OUT / "factor_etfs_vs_world.csv", index=False)
print(C.to_string(index=False, formatters={"CAGR": "{:.2%}".format, "vol": "{:.1%}".format, "Sharpe": "{:.2f}".format,
                                           "maxDD": "{:.1%}".format, "dCAGR": "{:+.2%}".format, "p_CAGR": "{:.3f}".format,
                                           "dSharpe": "{:+.2f}".format, "p_Sharpe": "{:.3f}".format}))
# equal-weight multi-factor blend (rebalanced monthly, cost ignored: <0.05%/yr at these drifts)
blend = E[["MOM", "QUALITY", "VALUE", "MINVOL"]].mean(axis=1)
m = metrics(blend, cash); c = compare(blend, E["WORLD_ETF"], cash, n_boot=3000)
print(f"  4-factor blend: CAGR {m['CAGR']:.2%} Sharpe {m['Sharpe']:.2f} maxDD {m['maxDD']:.1%} dCAGR {c['dCAGR']:+.2%} (p={c['p_CAGR']:.3f})")
