"""P10 (E015): volatility-managed leverage on the Nasdaq trend rule.

Pre-registration: research/AGENDA.md P10 (frozen in commit d85f0d1 before this ran).
Champion: synthetic 3x Nasdaq-100 held while the index is above its 100-day SMA, else cash
(h03_leveraged_trend.py, signal at close t, traded at close t+1).
Challenger: while the trend is on, weight in 3x = clip(tv / realised_vol_20d(3x), 0, 1), measured on
data through close t and traded at close t+1; the rest in the 1x index ("EQQQ") or cash. Off = cash.
Grid tv in {30%, 45%, 60%} x remainder {1x, cash} = 6 configs. Costs: 0.15% on every unit of weight
traded each day (daily rebalancing, no band - conservative), stress x3. Extra one-day lag as robustness.
Split IS 1986-2005, OOS 2006-2026. Run: python3 h09_vol_managed_leverage.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import h03_leveraged_trend as h03
from engine import compare, metrics
from h01_momentum_sleeve import p_dd50_10y
from h07_quality_momentum import dsr_cumulative

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
REG = HERE / "experiments"
TRIALS_BEFORE = 126
GRID = [(tv, rem) for tv in (0.30, 0.45, 0.60) for rem in ("1x", "cash")]
TRIALS_THIS_RUN = len(GRID)
COST = h03.SWITCH_COST
IS, OOS = ("1986-01-01", "2005-12-31"), ("2006-01-01", "2026-10-12")
REGIMES = [("1986-01-01", "2000-12-31"), ("2001-01-01", "2013-12-31"), ("2014-01-01", "2026-10-12")]


def series(r1, r3, rf, on, w3, rem, cost_mult=1.0, lag=2):
    """Daily returns. on/w3 are known at close t; positions earn from t+lag (lag=2 = traded at close t+1)."""
    p3 = (on * w3).shift(lag)
    prem = (on * (1 - w3)).shift(lag) if rem == "1x" else 0 * p3
    pc = 1 - p3 - prem
    idx = p3.dropna().index
    p3, prem, pc = p3[idx], prem[idx], pc[idx]
    ret = p3 * r3[idx] + prem * r1[idx] + pc * rf[idx]
    turn = p3.diff().abs().fillna(p3) + prem.diff().abs().fillna(prem)
    return ret - turn * COST * cost_mult, (turn.groupby(turn.index.year).sum().mean())


def monthly(d):
    return (1 + d).resample("ME").prod() - 1


def sl(s, a, b):
    return s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]


def main():
    r1 = h03.index_returns()
    rf = h03.daily_rf(r1.index)
    r3 = h03.leveraged(r1, rf)
    level = (1 + r1).cumprod()
    on = (level > level.rolling(100).mean()).astype(float)
    rv = r3.rolling(20).std() * np.sqrt(252)
    rf_m = monthly(rf)
    runs = {}
    for cm in (1.0, 3.0):
        runs[("champion", cm, 2)] = series(r1, r3, rf, on, pd.Series(1.0, index=r1.index), "cash", cm)
        for tv, rem in GRID:
            w3 = (tv / rv).clip(0, 1).fillna(0)
            runs[((tv, rem), cm, 2)] = series(r1, r3, rf, on, w3, rem, cm)
    for tv, rem in GRID:  # extra-lag robustness
        w3 = (tv / rv).clip(0, 1).fillna(0)
        runs[((tv, rem), 1.0, 3)] = series(r1, r3, rf, on, w3, rem, 1.0, lag=3)
    runs[("champion", 1.0, 3)] = series(r1, r3, rf, on, pd.Series(1.0, index=r1.index), "cash", 1.0, lag=3)

    rows = []
    for (cfg, cm, lag), (d, turn) in runs.items():
        name = "champion 3x SMA100" if cfg == "champion" else f"tv{int(cfg[0]*100)} rem={cfg[1]}"
        m = monthly(d)
        for per, (a, b) in (("IS", IS), ("OOS", OOS)):
            rows.append({"config": name, "cost_mult": cm, "lag_days": lag - 1, "period": per,
                         **metrics(sl(m, a, b), rf_m), "turnover_pa": turn})
    A = pd.DataFrame(rows)
    A.to_csv(OUT / "h09_all_configs.csv", index=False)

    base = A[(A.cost_mult == 1.0) & (A.lag_days == 1)]
    is_tab = base[(base.period == "IS") & (base.config != "champion 3x SMA100")]
    pick = is_tab.loc[is_tab.Sharpe.idxmax(), "config"]
    key = next(k for k in GRID if f"tv{int(k[0]*100)} rem={k[1]}" == pick)
    ch = monthly(runs[("champion", 1.0, 2)][0])
    r = monthly(runs[(key, 1.0, 2)][0])
    ro, cho = sl(r, *OOS), sl(ch, *OOS)
    mo, mc = metrics(ro, rf_m), metrics(cho, rf_m)
    c = compare(ro, cho, rf_m, n_boot=3000)
    irs = []
    for k in GRID:
        a = (sl(monthly(runs[(k, 1.0, 2)][0]), *OOS) - cho).dropna()
        irs.append(a.mean() / a.std())
    act = (ro - cho).dropna()
    dsr = dsr_cumulative(act.mean() / act.std(), len(act), float(act.skew()), float(act.kurt() + 3), np.array(irs),
                         TRIALS_BEFORE + TRIALS_THIS_RUN)
    m3 = metrics(sl(monthly(runs[(key, 3.0, 2)][0]), *OOS), rf_m)
    mc3 = metrics(sl(monthly(runs[("champion", 3.0, 2)][0]), *OOS), rf_m)
    neigh = [k for k in GRID if k[1] == key[1] and k != key]
    neigh_ok = all(metrics(sl(monthly(runs[(k, 1.0, 2)][0]), *OOS), rf_m)["Sharpe"] > mc["Sharpe"] and
                   metrics(sl(monthly(runs[(k, 1.0, 2)][0]), *OOS), rf_m)["CAGR"] > mc["CAGR"] for k in neigh)
    lag_m, lag_c = metrics(sl(monthly(runs[(key, 1.0, 3)][0]), *OOS), rf_m), metrics(sl(monthly(runs[("champion", 1.0, 3)][0]), *OOS), rf_m)
    reg = sum(metrics(sl(r, a, b), rf_m)["Sharpe"] > metrics(sl(ch, a, b), rf_m)["Sharpe"] for a, b in REGIMES)
    pdd_s, pdd_c = p_dd50_10y(sl(r, IS[0], OOS[1])), p_dd50_10y(sl(ch, IS[0], OOS[1]))
    tests = {"oos_beats": bool(mo["CAGR"] > mc["CAGR"] and mo["Sharpe"] > mc["Sharpe"] and min(c["p_CAGR"], c["p_Sharpe"]) < 0.10),
             "dsr_ge_0_90": bool(dsr >= 0.90),
             "costs_x3": bool(m3["CAGR"] > mc3["CAGR"] and m3["Sharpe"] > mc3["Sharpe"]),
             "neighbours": bool(neigh_ok),
             "maxdd_within_5pp": bool(mo["maxDD"] >= mc["maxDD"] - 0.05),
             "p_dd50_not_higher": bool(pdd_s <= pdd_c),
             "regimes_2_of_3": bool(reg >= 2),
             "extra_lag_still_beats": bool(lag_m["CAGR"] > lag_c["CAGR"] and lag_m["Sharpe"] > lag_c["Sharpe"])}
    G = pd.DataFrame([{"pick": pick, "CAGR": mo["CAGR"], "Sharpe": mo["Sharpe"], "maxDD": mo["maxDD"],
                       "champ_CAGR": mc["CAGR"], "champ_Sharpe": mc["Sharpe"], "champ_maxDD": mc["maxDD"],
                       "dCAGR": c["dCAGR"], "p_CAGR": c["p_CAGR"], "dSharpe": c["dSharpe"], "p_Sharpe": c["p_Sharpe"],
                       "DSR": dsr, "DSR_N": TRIALS_BEFORE + TRIALS_THIS_RUN, "CAGR_x3": m3["CAGR"], "champ_CAGR_x3": mc3["CAGR"],
                       "regime_wins": reg, "P_dd50_10y": pdd_s, "champ_P_dd50_10y": pdd_c,
                       **{f"t_{k}": v for k, v in tests.items()}, "PASS": all(tests.values())}])
    G.to_csv(OUT / "h09_gate.csv", index=False)
    pd.set_option("display.width", 250)
    print(base[["config", "period", "start", "end", "CAGR", "Sharpe", "maxDD", "turnover_pa"]].round(4).to_string(index=False))
    print(G.T.to_string())
    write_record()


def write_record():
    G = pd.read_csv(OUT / "h09_gate.csv").iloc[0]
    A = pd.read_csv(OUT / "h09_all_configs.csv")
    tests = {k[2:]: bool(G[k]) for k in G.index if k.startswith("t_")}
    failed = [k for k, v in tests.items() if not v]
    dd_cut = G.maxDD - G.champ_maxDD
    if G.PASS:
        decision, detail = "SHADOW", "Passed every Stage 2 test; add as shadow."
    elif dd_cut >= 0.10 and G.dCAGR < 0:
        decision = "INSURANCE_ONLY"
        detail = f"Failed: {', '.join(failed)}. Cuts OOS max drawdown {G.champ_maxDD:.1%} -> {G.maxDD:.1%} but CAGR {G.dCAGR:+.2%}/yr."
    else:
        decision, detail = "REJECTED", f"Failed Stage 2: {', '.join(failed)}."
    detail = (f"Pick {G.pick}. OOS 2006-2026: CAGR {G.CAGR:.1%} vs champion {G.champ_CAGR:.1%} (p={G.p_CAGR:.2f}), "
              f"Sharpe {G.Sharpe:.2f} vs {G.champ_Sharpe:.2f} (p={G.p_Sharpe:.2f}), maxDD {G.maxDD:.1%} vs {G.champ_maxDD:.1%}, "
              f"DSR {G.DSR:.2f} (N={int(G.DSR_N)}). ") + detail
    rr = lambda x, nd=4: None if pd.isna(x) else round(float(x), nd)
    rec = {"id": "E015", "title": "Volatility-managed leverage on the Nasdaq trend rule", "date": "2026-10-14", "agenda_item": "P10",
           "hypothesis": "Scaling 3x exposure by 20-day realised volatility while the trend is on beats constant 3x.",
           "rationale": "Moreira & Muir (2017): volatility-managed portfolios raise Sharpe; leveraged daily-reset drag grows with variance.",
           "data": ["Yahoo ^NDX 1985-1999, QQQ adjusted 1999-2026 (daily)", "Ken French daily-spread T-bill rate (via h03)"],
           "methodology": "Grid tv {30,45,60}% x remainder {1x, cash}, frozen in AGENDA P10 (commit d85f0d1); pick by IS Sharpe; full Stage 2.",
           "benchmark": "champion: 3x + SMA100, else cash (live rule before the discretionary override)",
           "costs": "0.15% per unit of weight traded, daily rebalancing; x3 stress; OCF and financing inside the synthetic 3x",
           "in_sample": "1986-2005", "out_of_sample": "2006-2026",
           "results": [{"config": r.config, "period": r.period, "cost_mult": r.cost_mult, "lag_days": int(r.lag_days),
                        "CAGR": rr(r.CAGR), "Sharpe": rr(r.Sharpe, 3), "maxDD": rr(r.maxDD), "turnover_pa": rr(r.turnover_pa, 2)}
                       for r in A.itertuples()],
           "gate": {"pick": G.pick, "dCAGR": rr(G.dCAGR), "p_CAGR": rr(G.p_CAGR, 3), "dSharpe": rr(G.dSharpe, 3), "p_Sharpe": rr(G.p_Sharpe, 3),
                    "DSR": rr(G.DSR, 3), "DSR_N": int(G.DSR_N), "regime_wins_of_3": int(G.regime_wins),
                    "P_dd50_10y": rr(G.P_dd50_10y, 3), "champion_P_dd50_10y": rr(G.champ_P_dd50_10y, 3), "tests": tests},
           "robustness": ["costs x3", "neighbouring tv", "extra one-day lag", "3 regimes", "bootstrap drawdown risk", "DSR at cumulative N"],
           "limitations": ["Synthetic 3x before 2012; USD, not the GBX line", "Daily rebalancing with no band overstates turnover",
                           "1x leg modelled as the index (QQQ/NDX), EQQQ tracking not modelled"],
           "trials": TRIALS_THIS_RUN, "decision": decision, "decision_detail": detail, "promoted": False,
           "evidence": ["research/h09_vol_managed_leverage.py", "research/output/h09_gate.csv", "research/output/h09_all_configs.csv"]}
    REG.joinpath("E015.json").write_text(json.dumps(rec, indent=1) + "\n")
    print("E015:", decision, "-", detail)


if __name__ == "__main__":
    main()
