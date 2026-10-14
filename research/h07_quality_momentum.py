"""P4 (E013): quality + momentum sleeve, vs the live champion and vs the previous champion.

Pre-registration: research/AGENDA.md, P4 (frozen in commit c4eb747 before this script was run).

Portfolios (static weights MKT/MOM/QUAL, monthly rebalance, long-only, no leverage):
  Q1 50/25/25 (the literal P4 rule: the 50% momentum sleeve split half momentum, half quality)
  Q2  0/50/50
  Q3 34/33/33
  Neighbours (knife-edge check only): Q1 50/30/20, 50/20/30; Q2 0/60/40, 0/40/60.
Pick per market = best in-sample Sharpe among Q1-Q3.

Data (Ken French, survivorship-free, value-weighted, USD, gross of fees):
  MKT  = Mkt-RF + RF; MOM = BIG HiPRIOR (6_Portfolios_ME_Prior_12_2);
  QUAL = BIG HiOP (6_Portfolios_ME_OP_2x3, large caps with robust operating profitability).
  Developed: Developed_3_Factors / Developed_6_Portfolios_ME_Prior_12_2 / Developed_6_Portfolios_ME_OP.
Benchmarks:
  (a) gate = live champion nasdaq3x_trend_sma100_v1: synthetic 3x Nasdaq-100 held while the index is
      above its 100-day SMA, one-day lag, costs (h03_leveraged_trend.py), compounded to months. USD.
  (b) design = previous champion 50% MKT + 50% MOM (what P4 was written to improve).
Costs: OCF MKT 0.22%, MOM 0.30%, QUAL 0.25% p.a.; one-way MKT 0.10%, MOM 0.35% (incl. FX), QUAL 0.20%,
       stress x3. Deflated Sharpe: cumulative trial count (AGENDA counter before this run + this run).

Run: python3 h07_quality_momentum.py   (writes research/output/h07_*.csv and experiments/E013.json)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

import h03_leveraged_trend as h03
from data_sources import french, yahoo
from dataset import clean_prices
from engine import compare, metrics
from h01_momentum_sleeve import p_dd50_10y

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
REG = HERE / "experiments"
LAST = "2026-08-31"
TRIALS_BEFORE = 106

A = ["MKT", "MOM", "QUAL", "CASH"]
OCF = {"MKT": 0.0022, "MOM": 0.0030, "QUAL": 0.0025, "CASH": 0.0}
TC = {"MKT": 0.0010, "MOM": 0.0035, "QUAL": 0.0020, "CASH": 0.0005}
SPLITS = {
    "US": {"is": ("1963-07-31", "2000-12-31"), "oos": ("2001-01-31", LAST),
           "regimes": [("1963-07-31", "1985-12-31"), ("1986-01-31", "2000-12-31"), ("2001-01-31", LAST)]},
    "DEV": {"is": ("1991-07-31", "2005-12-31"), "oos": ("2006-01-31", LAST),
            "regimes": [("1991-07-31", "2005-12-31"), ("2006-01-31", "2015-12-31"), ("2016-01-31", LAST)]},
}
CHAMP_REGIMES = [("1986-01-31", "2000-12-31"), ("2001-01-31", "2013-12-31"), ("2014-01-31", LAST)]

GRID = {"Q1 50/25/25": (0.50, 0.25, 0.25), "Q2 0/50/50": (0.0, 0.50, 0.50), "Q3 34/33/33": (0.34, 0.33, 0.33)}
NEIGH = {"Q1n 50/30/20": (0.50, 0.30, 0.20), "Q1n 50/20/30": (0.50, 0.20, 0.30),
         "Q2n 0/60/40": (0.0, 0.60, 0.40), "Q2n 0/40/60": (0.0, 0.40, 0.60)}
PREV = {"PREV 50/50": (0.50, 0.50, 0.0)}
CONFIGS = {**PREV, **GRID, **NEIGH}
TRIALS_THIS_RUN = (len(GRID) + len(NEIGH)) * 2


def market_data(mkt: str) -> pd.DataFrame:
    if mkt == "US":
        f, p, q = french("F-F_Research_Data_Factors"), french("6_Portfolios_ME_Prior_12_2"), french("6_Portfolios_ME_OP_2x3")
    else:
        f, p, q = french("Developed_3_Factors"), french("Developed_6_Portfolios_ME_Prior_12_2"), french("Developed_6_Portfolios_ME_OP")
    d = pd.DataFrame({"MKT": f["Mkt-RF"] + f["RF"], "MOM": p["BIG HiPRIOR"], "QUAL": q["BIG HiOP"], "CASH": f["RF"]}).dropna()
    d = d[d.index <= LAST]
    assert (d.abs() < 0.9).all().all(), "missing-value sentinel leaked into returns"
    return d


def backtest(R: pd.DataFrame, w_target, start, end=LAST, cost_mult=1.0):
    """Static target weights, rebalanced at each month-end; costs on one-way turnover from drifted weights."""
    w = pd.Series(dict(zip(["MKT", "MOM", "QUAL"], w_target)), dtype=float).reindex(A, fill_value=0.0)
    w["CASH"] = 1 - w[["MKT", "MOM", "QUAL"]].sum()
    assert abs(w.sum() - 1) < 1e-9 and (w >= -1e-12).all()
    out_r, out_t, prev = {}, {}, None
    for t1 in R.index[(R.index >= pd.Timestamp(start)) & (R.index <= pd.Timestamp(end))]:
        d = w if prev is None else w - prev
        turn = d.abs().sum() if prev is None else d.abs().sum() / 2
        tc = float((d.abs() * pd.Series(TC)).sum()) * cost_mult
        r1 = R.loc[t1, A] - pd.Series(OCF) / 12
        out_r[t1] = (1 - tc) * (1 + float((w * r1).sum())) - 1
        out_t[t1] = turn
        g = w * (1 + r1)
        prev = g / g.sum()
    return pd.Series(out_r), pd.Series(out_t)


def live_champion_monthly(cost_mult=1.0) -> pd.Series:
    """nasdaq3x_trend_sma100_v1 on synthetic 3x Nasdaq-100 (h03), compounded to month-end returns."""
    r1 = h03.index_returns()
    rf = h03.daily_rf(r1.index)
    r3 = h03.leveraged(r1, rf)
    level = (1 + r1).cumprod()
    sma = level.rolling(100).mean()
    pos = (level > sma).astype(float).shift(2).dropna()
    ret = pos * r3.reindex(pos.index) + (1 - pos) * rf.reindex(pos.index)
    ret = ret - pos.diff().abs().fillna(0) * h03.SWITCH_COST * cost_mult
    m = (1 + ret).resample("ME").prod() - 1
    return m[(m.index >= "1986-01-31") & (m.index <= LAST)]


def dsr_cumulative(sr_obs, n_obs, skew, kurt, sr_trials, n_trials):
    """Bailey & Lopez de Prado deflated Sharpe with N = cumulative trial count and the variance of this run's trials."""
    v = np.var(sr_trials, ddof=1)
    emc = 0.5772156649
    sr0 = np.sqrt(v) * ((1 - emc) * norm.ppf(1 - 1 / n_trials) + emc * norm.ppf(1 - 1 / (n_trials * np.e)))
    z = (sr_obs - sr0) * np.sqrt(n_obs - 1) / np.sqrt(1 - skew * sr_obs + (kurt - 1) / 4 * sr_obs ** 2)
    return float(norm.cdf(z))


def sl(s, a, b):
    return s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]


def gate_row(label, mkt, pick, r, ch, r3, ch3, cash, oos, regimes, neigh_rets, act_irs, full_start):
    ro, cho = sl(r, *oos), sl(ch, *oos)
    j = pd.concat([ro, cho], axis=1).dropna()
    ro, cho = j.iloc[:, 0], j.iloc[:, 1]
    mo, mc = metrics(ro, cash), metrics(cho, cash)
    c = compare(ro, cho, cash, n_boot=3000)
    act = ro - cho
    dsr = dsr_cumulative(act.mean() / act.std(), len(act), float(act.skew()), float(act.kurt() + 3),
                         np.array(act_irs), TRIALS_BEFORE + TRIALS_THIS_RUN)
    m3, mc3 = metrics(sl(r3, *oos).reindex(ro.index), cash), metrics(sl(ch3, *oos).reindex(ro.index), cash)
    neigh_beat = all(metrics(sl(n, *oos).reindex(ro.index), cash)["CAGR"] > mc["CAGR"]
                     and metrics(sl(n, *oos).reindex(ro.index), cash)["Sharpe"] > mc["Sharpe"] for n in neigh_rets)
    reg_wins = 0
    for a, b in regimes:
        x, y = sl(r, a, b), sl(ch, a, b)
        jj = pd.concat([x, y], axis=1).dropna()
        reg_wins += metrics(jj.iloc[:, 0], cash)["Sharpe"] > metrics(jj.iloc[:, 1], cash)["Sharpe"]
    fr, fc = pd.concat([sl(r, full_start, LAST), sl(ch, full_start, LAST)], axis=1).dropna().T.values
    pdd_s, pdd_c = p_dd50_10y(pd.Series(fr)), p_dd50_10y(pd.Series(fc))
    tests = {
        "oos_beats": bool(mo["CAGR"] > mc["CAGR"] and mo["Sharpe"] > mc["Sharpe"] and min(c["p_CAGR"], c["p_Sharpe"]) < 0.10),
        "dsr_ge_0_90": bool(dsr >= 0.90),
        "costs_x3": bool(m3["CAGR"] > mc3["CAGR"] and m3["Sharpe"] > mc3["Sharpe"]),
        "neighbours": bool(neigh_beat),
        "maxdd_within_5pp": bool(mo["maxDD"] >= mc["maxDD"] - 0.05),
        "p_dd50_not_higher": bool(pdd_s <= pdd_c),
        "regimes_2_of_3": bool(reg_wins >= 2),
    }
    return {"benchmark": label, "market": mkt, "pick": pick, "oos_start": ro.index[0].strftime("%Y-%m"),
            "oos_end": ro.index[-1].strftime("%Y-%m"), "CAGR": mo["CAGR"], "Sharpe": mo["Sharpe"], "maxDD": mo["maxDD"],
            "bench_CAGR": mc["CAGR"], "bench_Sharpe": mc["Sharpe"], "bench_maxDD": mc["maxDD"],
            "dCAGR": c["dCAGR"], "p_CAGR": c["p_CAGR"], "dSharpe": c["dSharpe"], "p_Sharpe": c["p_Sharpe"],
            "DSR_active": dsr, "DSR_trials_N": TRIALS_BEFORE + TRIALS_THIS_RUN,
            "CAGR_x3": m3["CAGR"], "bench_CAGR_x3": mc3["CAGR"], "regime_wins": reg_wins,
            "P_dd50_10y": pdd_s, "bench_P_dd50_10y": pdd_c,
            **{f"t_{k}": v for k, v in tests.items()}, "PASS": all(tests.values())}


def main():
    rows, rets, gate = [], {}, []
    champ, champ3 = live_champion_monthly(1.0), live_champion_monthly(3.0)
    for mkt, sp in SPLITS.items():
        R = market_data(mkt)
        cash = R["CASH"]
        for name, w in CONFIGS.items():
            for cm in (1.0, 3.0):
                r, t = backtest(R, w, sp["is"][0], cost_mult=cm)
                rets[(mkt, name, cm)] = r
                for per, (a, b) in {"IS": sp["is"], "OOS": sp["oos"]}.items():
                    rows.append({"market": mkt, "config": name, "cost_mult": cm, "period": per, **metrics(sl(r, a, b), cash, t)})
        if mkt == "US":
            for cm, s in ((1.0, champ), (3.0, champ3)):
                for per, (a, b) in {"IS": ("1986-01-31", sp["is"][1]), "OOS": sp["oos"]}.items():
                    rows.append({"market": mkt, "config": "LIVE CHAMPION 3x NDX SMA100", "cost_mult": cm, "period": per,
                                 **metrics(sl(s, a, b), cash)})
    allc = pd.DataFrame(rows)
    allc.to_csv(OUT / "h07_all_configs.csv", index=False)

    is_tab = allc[(allc.period == "IS") & (allc.cost_mult == 1.0)]
    for mkt, sp in SPLITS.items():
        R = market_data(mkt)
        cash = R["CASH"]
        sub = is_tab[(is_tab.market == mkt) & is_tab.config.isin(list(GRID))]
        pick = sub.loc[sub.Sharpe.idxmax(), "config"]
        fam = pick.split()[0]
        neigh = [rets[(mkt, n, 1.0)] for n in NEIGH if n.startswith(fam + "n")]
        if not neigh:  # Q3 has no pre-registered neighbours: use Q1's and Q2's (all other weightings)
            neigh = [rets[(mkt, n, 1.0)] for n in list(GRID) + list(NEIGH) if n != pick]
        r, r3 = rets[(mkt, pick, 1.0)], rets[(mkt, pick, 3.0)]
        trial_names = list(GRID) + list(NEIGH)
        benches = [("prev_champion_50_50", rets[(mkt, "PREV 50/50", 1.0)], rets[(mkt, "PREV 50/50", 3.0)],
                    sp["regimes"], sp["is"][0])]
        if mkt == "US":
            benches.insert(0, ("live_champion_3x_ndx_sma100", champ, champ3, CHAMP_REGIMES, "1986-01-31"))
        for label, ch, ch3, regs, fs in benches:
            irs = []
            for n in trial_names:
                a = sl(rets[(mkt, n, 1.0)] - ch, *sp["oos"]).dropna()
                irs.append(a.mean() / a.std())
            gate.append(gate_row(label, mkt, pick, r, ch, r3, ch3, cash, sp["oos"], regs, neigh, irs, fs))
    G = pd.DataFrame(gate)
    G.to_csv(OUT / "h07_gate.csv", index=False)
    T = tradeable_check()
    T.to_csv(OUT / "h07_tradeable.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    show = ["config", "cost_mult", "period", "start", "end", "CAGR", "Sharpe", "maxDD", "turnover_pa"]
    for mkt in SPLITS:
        print(mkt)
        print(allc[(allc.market == mkt) & (allc.cost_mult == 1.0)][show].round(4).to_string(index=False))
    print(G.drop(columns=[c for c in G.columns if c.startswith("t_")]).round(4).to_string(index=False))
    print(G[["benchmark", "market"] + [c for c in G.columns if c.startswith("t_")]].to_string(index=False))
    print(T.round(4).to_string(index=False))
    print("trials this run:", TRIALS_THIS_RUN, "cumulative:", TRIALS_BEFORE + TRIALS_THIS_RUN)
    write_record()


def tradeable_check() -> pd.DataFrame:
    px = {k: clean_prices(yahoo(s)["adjclose"]) for k, s in (("MKT", "VWRL.L"), ("MOM", "IWFM.L"), ("QUAL", "IWFQ.L"))}
    P = pd.DataFrame(px).dropna()
    P = P[(P.index >= "2014-11-01") & (P.index <= LAST)]
    D = P.pct_change().dropna()
    month_ends = P.resample("ME").last().index
    rows = []
    for name, w in {**PREV, **GRID}.items():
        w = pd.Series(dict(zip(["MKT", "MOM", "QUAL"], w)))
        for lag in (0, 1):
            # monthly rebalance to target, drift in between; rebalance on the (lag)th trading day after month-end
            reb = set()
            for t in month_ends:
                after = D.index[D.index > t]
                if len(after) > lag:
                    reb.add(after[lag])
            cur, out = None, []
            for d in D.index:
                tc = 0.0
                if cur is None or d in reb:
                    delta = w - (cur if cur is not None else 0.0)
                    tc = float((delta.abs() * pd.Series(TC)[w.index]).sum())
                    cur = w.copy()
                rr = float((cur * D.loc[d, w.index]).sum())
                out.append((1 - tc) * (1 + rr) - 1)
                g = cur * (1 + D.loc[d, w.index])
                cur = g / g.sum()
            dr = pd.Series(out, index=D.index)
            eq = (1 + dr).cumprod()
            yrs = len(dr) / 252
            rows.append({"config": name, "exec_lag_days": lag, "start": str(dr.index[0].date()), "end": str(dr.index[-1].date()),
                         "CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "vol": dr.std() * np.sqrt(252),
                         "Sharpe_raw": dr.mean() / dr.std() * np.sqrt(252), "maxDD": (eq / eq.cummax() - 1).min()})
    # live rule on real LQQ3 (GBP), same window, from h03's real-fund logic
    lq = yahoo("LQQ3.L")["adjclose"]
    lq = lq[lq.index >= "2013-01-01"].where(lambda x: x > 0).dropna()
    r = lq.pct_change()
    r = r[r.abs() < 0.35].dropna()
    q = yahoo("QQQ")["adjclose"]
    on = (q > q.rolling(100).mean()).astype(float)
    pos = on.reindex(r.index, method="ffill").shift(2).fillna(0.0)
    strat = (pos * r - pos.diff().abs().fillna(0) * h03.SWITCH_COST)
    strat = strat[(strat.index >= D.index[0]) & (strat.index <= D.index[-1])]
    eq = (1 + strat).cumprod()
    yrs = len(strat) / 252
    rows.append({"config": "LIVE CHAMPION real LQQ3 + SMA100 (GBP)", "exec_lag_days": 1, "start": str(strat.index[0].date()),
                 "end": str(strat.index[-1].date()), "CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "vol": strat.std() * np.sqrt(252),
                 "Sharpe_raw": strat.mean() / strat.std() * np.sqrt(252), "maxDD": (eq / eq.cummax() - 1).min()})
    return pd.DataFrame(rows)


def write_record():
    G = pd.read_csv(OUT / "h07_gate.csv")
    T = pd.read_csv(OUT / "h07_tradeable.csv")

    def rr(x, nd=4):
        return None if pd.isna(x) else round(float(x), nd)

    results = [{"benchmark": g.benchmark, "market": g.market, "pick_on_IS_sharpe": g.pick, "oos": f"{g.oos_start}..{g.oos_end}",
                "CAGR": rr(g.CAGR), "Sharpe": rr(g.Sharpe, 3), "maxDD": rr(g.maxDD),
                "benchmark_CAGR": rr(g.bench_CAGR), "benchmark_Sharpe": rr(g.bench_Sharpe, 3), "benchmark_maxDD": rr(g.bench_maxDD),
                "dCAGR": rr(g.dCAGR), "p_CAGR": rr(g.p_CAGR, 3), "dSharpe": rr(g.dSharpe, 3), "p_Sharpe": rr(g.p_Sharpe, 3),
                "DSR_active": rr(g.DSR_active, 3), "DSR_trials_N": int(g.DSR_trials_N), "regime_wins_of_3": int(g.regime_wins),
                "P_dd50_10y": rr(g.P_dd50_10y, 3), "benchmark_P_dd50_10y": rr(g.bench_P_dd50_10y, 3),
                "tests": {c[2:]: bool(getattr(g, c)) for c in G.columns if c.startswith("t_")}, "PASS": bool(g.PASS)}
               for g in G.itertuples()]
    live = G[G.benchmark == "live_champion_3x_ndx_sma100"]
    prev = G[G.benchmark == "prev_champion_50_50"]
    if live.PASS.all():
        decision, detail = "SHADOW", "Passed every Stage 2 test vs the live champion."
    else:
        failed = sorted({c[2:] for c in G.columns if c.startswith("t_") for g in live.itertuples() if not getattr(g, c)})
        detail = "Failed Stage 2 vs the live champion (US OOS): " + ", ".join(failed) + "."
        pf = sorted({c[2:] for c in G.columns if c.startswith("t_") for g in prev.itertuples() if not getattr(g, c)})
        detail += (" Vs the previous champion 50/50 (both markets): " +
                   ("passes every test." if prev.PASS.all() else "fails " + ", ".join(pf) + "."))
        decision = "REJECTED"
    rec = {
        "id": "E013", "title": "Quality + momentum sleeve", "date": "2026-10-14", "agenda_item": "P4",
        "hypothesis": "Splitting the momentum sleeve between momentum and quality (profitability) raises risk-adjusted returns "
                      "because quality hedges momentum crashes.",
        "rationale": "Quality/profitability tends to hold up in momentum crashes and junk rallies; RMW still significant post-2010.",
        "data": ["Ken French Data Library: F-F_Research_Data_Factors, 6_Portfolios_ME_Prior_12_2, 6_Portfolios_ME_OP_2x3, "
                 "Developed_3_Factors, Developed_6_Portfolios_ME_Prior_12_2, Developed_6_Portfolios_ME_OP (USD, to 2026-08)",
                 "Yahoo ^NDX / QQQ daily (live champion, via h03_leveraged_trend.py)",
                 "Yahoo adjusted closes VWRL.L, IWFM.L, IWFQ.L, LQQ3.L 2014-11..2026-08 for the tradeable check"],
        "methodology": "Pre-registered grid Q1 50/25/25, Q2 0/50/50, Q3 34/33/33 (MKT/MOM/QUAL) + 4 neighbours; pick by "
                       "in-sample Sharpe; Stage 2 vs the live champion (US) and vs the previous champion (US, Developed).",
        "benchmark": "Gate: live champion nasdaq3x_trend_sma100_v1 (synthetic 3x Nasdaq-100 + SMA100, monthly). "
                     "Information: previous champion 50% MKT + 50% MOM.",
        "costs": "OCF MKT 0.22%, MOM 0.30%, QUAL 0.25% p.a.; one-way MKT 0.10%, MOM 0.35%, QUAL 0.20%; stress x3",
        "in_sample": "US 1963-07..2000-12 (live champion from 1986); Developed 1991-07..2005-12",
        "out_of_sample": "US 2001-01..2026-08; Developed 2006-01..2026-08",
        "results": results,
        "tradeable_check": [{"config": t.config, "exec_lag_days": int(t.exec_lag_days), "start": t.start, "end": t.end,
                             "CAGR": rr(t.CAGR), "maxDD": rr(t.maxDD)} for t in T.itertuples()],
        "robustness": ["costs x3", "neighbouring weights", "3 sub-period regimes", "bootstrap P(>=50% drawdown in 10y)",
                       "deflated Sharpe with cumulative trial count", "tradeable GBP ETF check with same-day and next-day execution"],
        "limitations": ["USD academic portfolios; the live champion is also in USD here, the real fund is GBX",
                        "BIG HiOP (operating profitability) is a proxy for MSCI World Quality (ROE, leverage, earnings variability)",
                        "The live champion was installed by owner override (E009), not via the gate; comparing an unlevered "
                        "portfolio against a 3x strategy mostly measures leverage, not the quality effect"],
        "trials": TRIALS_THIS_RUN, "decision": decision, "decision_detail": detail, "promoted": False,
        "evidence": ["research/h07_quality_momentum.py", "research/output/h07_gate.csv", "research/output/h07_all_configs.csv",
                     "research/output/h07_tradeable.csv"],
    }
    REG.joinpath("E013.json").write_text(json.dumps(rec, indent=1) + "\n")
    print("E013:", decision, "-", detail)


if __name__ == "__main__":
    main()
