"""Phase 2: asset-allocation strategy families, IS selection -> OOS evaluation."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from data_sources import DATA
from dataset import build
from engine import IS_END, OOS_START, compare, deflated_sharpe, metrics, run
from strategies import grid

OUT = DATA.parent / "output"
IS_START = "1992-01-31"

R = build()
R.to_csv(DATA / "monthly_gbp_returns.csv")
cash = R["CASH"]
G = grid()

rows, results = [], {}
for fam, name, fn in G:
    res = run(name, R, fn, start=IS_START)
    results[name] = (fam, res)
    for period, (a, b) in {"IS": (IS_START, IS_END), "OOS": (OOS_START, None), "FULL": (IS_START, None)}.items():
        r = res.returns[(res.returns.index >= a) & ((b is None) | (res.returns.index <= (b or "2100")))]
        m = metrics(r, cash, res.turnover)
        rows.append({"family": fam, "strategy": name, "period": period, **m})
tab = pd.DataFrame(rows)
tab.to_csv(OUT / "allocation_all_configs.csv", index=False)

# --- selection rule (pre-declared): best IS Sharpe within each family
is_tab = tab[tab.period == "IS"].set_index("strategy")
picks = {}
for fam in tab.family.unique():
    sub = is_tab[is_tab.family == fam]
    picks[fam] = sub["Sharpe"].idxmax()

bench = results["WORLD buy&hold"][1].returns
summary = []
n_trials = len(G) - 2
is_monthly_sr = []
for name, (fam, res) in results.items():
    r = res.returns[(res.returns.index >= IS_START) & (res.returns.index <= IS_END)]
    e = r - cash.reindex(r.index)
    is_monthly_sr.append(e.mean() / e.std())
is_monthly_sr = np.array(is_monthly_sr)

for fam, name in picks.items():
    res = results[name][1]
    for period, (a, b) in {"IS": (IS_START, IS_END), "OOS": (OOS_START, "2100-01-01")}.items():
        r = res.returns[(res.returns.index >= a) & (res.returns.index <= b)]
        rb = bench.reindex(r.index)
        m = metrics(r, cash, res.turnover)
        c = compare(r, rb, cash) if name != "WORLD buy&hold" else {}
        e = r - cash.reindex(r.index)
        dsr = deflated_sharpe(e.mean() / e.std(), len(e), float(e.skew()), float(e.kurt() + 3), is_monthly_sr) if period == "IS" else np.nan
        summary.append({"family": fam, "strategy": name, "period": period, **m, **c, "DSR": dsr})
S = pd.DataFrame(summary)
S.to_csv(OUT / "allocation_selected.csv", index=False)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
fmt = {"CAGR": "{:.2%}", "vol": "{:.2%}", "maxDD": "{:.1%}", "worst12m": "{:.1%}", "Sharpe": "{:.2f}", "Sortino": "{:.2f}",
       "Calmar": "{:.2f}", "turnover_pa": "{:.2f}", "dSharpe": "{:+.2f}", "p_Sharpe": "{:.3f}", "dCAGR": "{:+.2%}", "p_CAGR": "{:.3f}", "DSR": "{:.3f}"}
show = S[["family", "strategy", "period", "start", "end", "CAGR", "vol", "Sharpe", "maxDD", "worst12m", "turnover_pa", "dSharpe", "p_Sharpe", "dCAGR", "p_CAGR", "DSR"]].copy()
for k, f in fmt.items():
    if k in show:
        show[k] = show[k].map(lambda v, f=f: "" if pd.isna(v) else f.format(v))
print(show.to_string(index=False))
print()
print("Full grid OOS Sharpe ranking (for transparency, NOT used for selection):")
o = tab[tab.period == "OOS"].sort_values("Sharpe", ascending=False)[["strategy", "CAGR", "Sharpe", "maxDD"]]
print(o.head(12).to_string(index=False, formatters={"CAGR": "{:.2%}".format, "Sharpe": "{:.2f}".format, "maxDD": "{:.1%}".format}))
print("...")
print(o.tail(5).to_string(index=False, formatters={"CAGR": "{:.2%}".format, "Sharpe": "{:.2f}".format, "maxDD": "{:.1%}".format}))
json.dump(picks, open(OUT / "allocation_picks.json", "w"), indent=1)
