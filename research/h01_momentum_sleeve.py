"""P1 (E006) and P2 (E007): can the momentum sleeve of the champion be managed better?

Champion  : 50% MKT + 50% MOM, rebalanced monthly (momentum_tilt_v1).
P1 (E006) : MOM weight = clip(tv / realised_vol(MOM - MKT, 6m), 0.25, 0.75), rest MKT.
            Pre-registered grid tv in {6%, 8%, 10%} (AGENDA P1).
P2 (E007) : if MKT's total-return index is below its 10-month SMA, the MOM sleeve moves to
            MKT (variant "to_mkt") or to cash (variant "to_cash"). Neighbours SMA 8 and 12
            are run only as the Stage 2 knife-edge check.

Data (survivorship-free, value-weighted, USD, gross of fees; Ken French Data Library):
  US  : MKT = Mkt-RF + RF; MOM = 6_Portfolios_ME_Prior_12_2 "BIG HiPRIOR" (large caps, top 30%
        by 12-2 momentum, the closest public analogue of MSCI World Momentum). 1927-2026.
  DEV : same from Developed_3_Factors / Developed_6_Portfolios_ME_Prior_12_2. 1990-2026.
  Tradeable check: IWFM.L (MSCI World Momentum, GBX) vs VWRL.L (FTSE All-World, GBP), daily,
        2014-2026, with month-end signal executed at the next day's close.

Splits (pre-registered): US IS 1927-2000, OOS 2001-2026. DEV IS 1991-2005, OOS 2006-2026.
Selection: per hypothesis and market, the config with the best in-sample Sharpe is the pick.
Decision rule (fixed before OOS): a pick passes only if it clears every Stage 2 test in
research/PROMOTION_GATE.md in BOTH markets.

Costs: fund OCF haircut (MKT 0.22%, MOM 0.30% p.a.) on every month held; one-way trading cost
MKT 0.10%, MOM 0.35% (0.20% spread + 0.15% FX on the USD line IWMO), CASH 0.05%. Stress: x3.

Run: python3 h01_momentum_sleeve.py   (writes research/output/h01_*.csv, experiments/E006/E007)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources import french, yahoo
from dataset import clean_prices
from engine import compare, deflated_sharpe, metrics

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
REG = HERE / "experiments"
LAST = "2026-08-31"  # last month in the Ken French files pulled 2026-10-13

OCF = {"MKT": 0.0022, "MOM": 0.0030, "CASH": 0.0}
TC = {"MKT": 0.0010, "MOM": 0.0035, "CASH": 0.0005}
SPLITS = {
    "US": {"is": ("1927-07-31", "2000-12-31"), "oos": ("2001-01-31", LAST),
           "regimes": [("1927-07-31", "1962-12-31"), ("1963-01-31", "2000-12-31"), ("2001-01-31", LAST)]},
    "DEV": {"is": ("1991-06-30", "2005-12-31"), "oos": ("2006-01-31", LAST),
            "regimes": [("1991-06-30", "2005-12-31"), ("2006-01-31", "2015-12-31"), ("2016-01-31", LAST)]},
}


# ------------------------------------------------------------------ data

def market_data(mkt: str) -> pd.DataFrame:
    if mkt == "US":
        f, p = french("F-F_Research_Data_Factors"), french("6_Portfolios_ME_Prior_12_2")
    else:
        f, p = french("Developed_3_Factors"), french("Developed_6_Portfolios_ME_Prior_12_2")
    d = pd.DataFrame({"MKT": f["Mkt-RF"] + f["RF"], "MOM": p["BIG HiPRIOR"], "CASH": f["RF"]}).dropna()
    d = d[d.index <= LAST]
    assert (d.abs() < 0.9).all().all(), "missing-value sentinel leaked into returns"
    return d


# ------------------------------------------------------------------ rules (see only data through t)

def champion(h):
    return {"MKT": 0.5, "MOM": 0.5}


def vol_managed(tv, L=6):
    def f(h):
        rel = (h["MOM"] - h["MKT"]).iloc[-L:]
        if len(rel) < L:
            return None
        rv = rel.std() * np.sqrt(12)
        w = float(np.clip(tv / rv, 0.25, 0.75)) if rv > 0 else 0.75
        return {"MKT": 1 - w, "MOM": w}
    return f


def trend_filtered(L=10, to="MKT"):
    def f(h):
        x = h["MKT"]
        if len(x) < L:
            return None
        idx = (1 + x).cumprod()
        if idx.iloc[-1] > idx.iloc[-L:].mean():
            return {"MKT": 0.5, "MOM": 0.5}
        return {"MKT": 1.0} if to == "MKT" else {"MKT": 0.5, "CASH": 0.5}
    return f


# ------------------------------------------------------------------ backtest

def backtest(R: pd.DataFrame, fn, start, end=LAST, cost_mult=1.0, warmup=12):
    """Weights decided at month-end t from R[:t] earn month t+1. Costs on one-way turnover
    from drifted weights; OCF charged monthly on holdings."""
    out_r, out_w, out_t = {}, {}, {}
    prev = None
    dates = R.index[(R.index >= pd.Timestamp(start)) & (R.index <= pd.Timestamp(end))]
    for t1 in dates:
        i = R.index.get_loc(t1)
        if i < warmup:
            continue
        w = fn(R.iloc[:i])
        if w is None:
            continue
        w = pd.Series(w, dtype=float).reindex(["MKT", "MOM", "CASH"], fill_value=0.0)
        assert abs(w.sum() - 1) < 1e-9 and (w >= 0).all()
        d = w if prev is None else (w - prev)
        turn = d.abs().sum() if prev is None else d.abs().sum() / 2
        tc = float((d.abs() * pd.Series(TC)).sum()) * cost_mult
        r1 = R.loc[t1, ["MKT", "MOM", "CASH"]] - pd.Series(OCF) / 12
        gross = float((w * r1).sum())
        out_r[t1] = (1 - tc) * (1 + gross) - 1
        out_w[t1], out_t[t1] = w, turn
        grown = w * (1 + r1)
        prev = grown / grown.sum()
    return pd.Series(out_r), pd.DataFrame(out_w).T, pd.Series(out_t)


def p_dd50_10y(r: pd.Series, n_boot=4000, seed=11):
    """Stationary-bootstrap probability of a >=50% drawdown within 10 years."""
    rng = np.random.default_rng(seed)
    x = r.values
    n, p = len(x), 1 / 12  # mean block length 12 months, drawn from the whole history
    hits = 0
    for _ in range(n_boot):
        idx = np.empty(120, dtype=int)
        idx[0] = rng.integers(n)
        for i in range(1, 120):
            idx[i] = rng.integers(n) if rng.random() < p else (idx[i - 1] + 1) % n
        path = np.cumprod(1 + x[idx])
        hits += (path / np.maximum.accumulate(np.r_[1.0, path])[1:]).min() <= 0.5
    return hits / n_boot


# ------------------------------------------------------------------ configs

P1 = {f"P1 volmgd tv={int(tv*100)}%": vol_managed(tv) for tv in (0.06, 0.08, 0.10)}
P2 = {f"P2 SMA10 to_{to.lower()}": trend_filtered(10, to) for to in ("MKT", "CASH")}
NEIGH = {f"P2 SMA{L} to_{to.lower()}": trend_filtered(L, to) for L in (8, 12) for to in ("MKT", "CASH")}
CONFIGS = {"CHAMPION 50/50": champion, **P1, **P2, **NEIGH}
TRIALS_THIS_RUN = len(P1) * 2 + len(P2) * 2 + len(NEIGH) * 2  # every non-champion config x 2 markets


def sl(s, a, b):
    return s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]


def main():
    rows, active_ir = [], {}
    rets = {}
    for mkt, sp in SPLITS.items():
        R = market_data(mkt)
        cash = R["CASH"]
        for name, fn in CONFIGS.items():
            for cm in (1.0, 3.0):
                r, w, t = backtest(R, fn, sp["is"][0], cost_mult=cm)
                rets[(mkt, name, cm)] = r
                for per, (a, b) in {"IS": sp["is"], "OOS": sp["oos"]}.items():
                    m = metrics(sl(r, a, b), cash, t)
                    rows.append({"market": mkt, "config": name, "cost_mult": cm, "period": per,
                                 "avg_mom_weight": float(sl(w["MOM"], a, b).mean()), **m})
        # active-return information ratio (OOS) of every non-champion config, for the deflated Sharpe
        ch = rets[(mkt, "CHAMPION 50/50", 1.0)]
        for name in CONFIGS:
            if name.startswith("CHAMPION"):
                continue
            act = sl(rets[(mkt, name, 1.0)] - ch, *sp["oos"]).dropna()
            active_ir[(mkt, name)] = act.mean() / act.std() if act.std() > 0 else 0.0
    allc = pd.DataFrame(rows)
    allc.to_csv(OUT / "h01_all_configs.csv", index=False)

    # ---- picks on in-sample Sharpe (base costs), then the Stage 2 battery
    is_tab = allc[(allc.period == "IS") & (allc.cost_mult == 1.0)]
    gate = []
    ir_all = np.array(list(active_ir.values()))
    for hyp, names in (("P1", list(P1)), ("P2", list(P2))):
        for mkt, sp in SPLITS.items():
            R = market_data(mkt)
            cash = R["CASH"]
            sub = is_tab[(is_tab.market == mkt) & (is_tab.config.isin(names))]
            pick = sub.loc[sub.Sharpe.idxmax(), "config"]
            r, ch = rets[(mkt, pick, 1.0)], rets[(mkt, "CHAMPION 50/50", 1.0)]
            ro, cho = sl(r, *sp["oos"]), sl(ch, *sp["oos"])
            mo, mc = metrics(ro, cash), metrics(cho, cash)
            c = compare(ro, cho, cash, n_boot=3000)
            act = (ro - cho).dropna()
            dsr = deflated_sharpe(act.mean() / act.std(), len(act), float(act.skew()), float(act.kurt() + 3), ir_all)
            # costs x3
            r3, ch3 = sl(rets[(mkt, pick, 3.0)], *sp["oos"]), sl(rets[(mkt, "CHAMPION 50/50", 3.0)], *sp["oos"])
            m3, mc3 = metrics(r3, cash), metrics(ch3, cash)
            # neighbours: every other config of the same hypothesis family (P1 grid; P2 SMA 8/12, same variant)
            if hyp == "P1":
                neigh = [n for n in P1 if n != pick]
            else:
                variant = pick.split()[-1]
                neigh = [n for n in NEIGH if n.endswith(variant)]
            neigh_beat = all(metrics(sl(rets[(mkt, n, 1.0)], *sp["oos"]), cash)["Sharpe"] > mc["Sharpe"] for n in neigh)
            # regimes (full history, base costs): beats champion on Sharpe in >= 2 of 3
            reg_wins = sum(metrics(sl(r, a, b), cash)["Sharpe"] > metrics(sl(ch, a, b), cash)["Sharpe"] for a, b in sp["regimes"])
            full_r, full_c = sl(r, sp["is"][0], LAST), sl(ch, sp["is"][0], LAST)
            pdd_s, pdd_c = p_dd50_10y(full_r), p_dd50_10y(full_c)
            tests = {
                "oos_beats": bool(mo["CAGR"] > mc["CAGR"] and mo["Sharpe"] > mc["Sharpe"] and min(c["p_CAGR"], c["p_Sharpe"]) < 0.10),
                "dsr_ge_0_90": bool(dsr >= 0.90),
                "costs_x3": bool(m3["CAGR"] > mc3["CAGR"] and m3["Sharpe"] > mc3["Sharpe"]),
                "neighbours": bool(neigh_beat),
                "maxdd_within_5pp": bool(mo["maxDD"] >= mc["maxDD"] - 0.05),
                "p_dd50_not_higher": bool(pdd_s <= pdd_c),
                "regimes_2_of_3": bool(reg_wins >= 2),
            }
            gate.append({"hypothesis": hyp, "market": mkt, "pick": pick, "oos": f"{sp['oos'][0][:7]}..{sp['oos'][1][:7]}",
                         "CAGR": mo["CAGR"], "Sharpe": mo["Sharpe"], "maxDD": mo["maxDD"],
                         "champ_CAGR": mc["CAGR"], "champ_Sharpe": mc["Sharpe"], "champ_maxDD": mc["maxDD"],
                         "dCAGR": c["dCAGR"], "p_CAGR": c["p_CAGR"], "dSharpe": c["dSharpe"], "p_Sharpe": c["p_Sharpe"],
                         "DSR_active": dsr, "CAGR_x3": m3["CAGR"], "champ_CAGR_x3": mc3["CAGR"],
                         "regime_wins": reg_wins, "P_dd50_10y": pdd_s, "champ_P_dd50_10y": pdd_c,
                         "turnover_pa": float(allc[(allc.market == mkt) & (allc.config == pick) & (allc.period == "OOS") & (allc.cost_mult == 1.0)].turnover_pa.iloc[0]),
                         **{f"t_{k}": v for k, v in tests.items()}, "PASS": all(tests.values())})
    G = pd.DataFrame(gate)
    G.to_csv(OUT / "h01_gate.csv", index=False)

    # ---- tradeable ETF check, daily, month-end signal executed next day vs same day
    G2 = tradeable_check()
    G2.to_csv(OUT / "h01_tradeable.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(G.drop(columns=[c for c in G.columns if c.startswith("t_")]).round(4).to_string(index=False))
    print(G[["hypothesis", "market"] + [c for c in G.columns if c.startswith("t_")]].to_string(index=False))
    print(G2.round(4).to_string(index=False))
    print("trials this run:", TRIALS_THIS_RUN)
    write_records()


def tradeable_check() -> pd.DataFrame:
    px = {}
    for k, sym in (("MKT", "VWRL.L"), ("MOM", "IWFM.L")):
        s = clean_prices(yahoo(sym)["adjclose"])
        px[k] = s
    P = pd.DataFrame(px).dropna()
    P = P[(P.index >= "2014-11-01") & (P.index <= LAST)]
    D = P.pct_change().dropna()
    M = P.resample("ME").last().pct_change().dropna()
    M["CASH"] = 0.0  # only the MKT/MOM split matters here; to_cash variant omitted (no GBP cash leg)
    rows = []
    names = {"CHAMPION 50/50": champion, **P1, "P2 SMA10 to_mkt": trend_filtered(10, "MKT")}
    for name, fn in names.items():
        for lag in (0, 1):
            w_daily = pd.DataFrame(index=D.index, columns=["MKT", "MOM"], dtype=float)
            for t in M.index[6:]:
                w = fn(M.loc[:t])
                if w is None:
                    continue
                after = D.index[D.index > t]
                if len(after) <= lag:
                    continue
                w_daily.loc[after[lag]:, "MKT"] = w.get("MKT", 0.0)
                w_daily.loc[after[lag]:, "MOM"] = w.get("MOM", 0.0)
            w_daily = w_daily.dropna()
            # daily rebalanced to target is a close approximation of monthly over 1-month horizons
            dr = (w_daily * D.loc[w_daily.index]).sum(axis=1)
            chg = w_daily.diff().abs().fillna(w_daily.abs())
            dr = dr - (chg["MKT"] * TC["MKT"] + chg["MOM"] * TC["MOM"])  # ETF prices are already net of OCF
            eq = (1 + dr).cumprod()
            yrs = len(dr) / 252
            rows.append({"config": name, "exec_lag_days": lag, "start": str(dr.index[0].date()), "end": str(dr.index[-1].date()),
                         "CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "vol": dr.std() * np.sqrt(252),
                         "Sharpe_raw": dr.mean() / dr.std() * np.sqrt(252), "maxDD": (eq / eq.cummax() - 1).min(),
                         "avg_mom_weight": w_daily["MOM"].mean()})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ registry records (numbers read back from CSV)

def write_records():
    G = pd.read_csv(OUT / "h01_gate.csv")
    T = pd.read_csv(OUT / "h01_tradeable.csv")

    def rr(x, nd=4):
        return None if pd.isna(x) else round(float(x), nd)

    def block(hyp):
        out = []
        for row in G[G.hypothesis == hyp].itertuples():
            out.append({"market": row.market, "pick_on_IS_sharpe": row.pick, "oos": row.oos,
                        "CAGR": rr(row.CAGR), "Sharpe": rr(row.Sharpe, 3), "maxDD": rr(row.maxDD),
                        "champion_CAGR": rr(row.champ_CAGR), "champion_Sharpe": rr(row.champ_Sharpe, 3), "champion_maxDD": rr(row.champ_maxDD),
                        "dCAGR": rr(row.dCAGR), "p_CAGR": rr(row.p_CAGR, 3), "dSharpe": rr(row.dSharpe, 3), "p_Sharpe": rr(row.p_Sharpe, 3),
                        "DSR_active": rr(row.DSR_active, 3), "regime_wins_of_3": int(row.regime_wins),
                        "P_dd50_10y": rr(row.P_dd50_10y, 3), "champion_P_dd50_10y": rr(row.champ_P_dd50_10y, 3),
                        "tests": {c[2:]: bool(getattr(row, c)) for c in G.columns if c.startswith("t_")}, "PASS": bool(row.PASS)})
        return out

    def tradeable(prefix):
        sel = T[T.config.str.startswith(prefix) | T.config.str.startswith("CHAMPION")]
        return [{"config": r.config, "exec_lag_days": int(r.exec_lag_days), "CAGR": rr(r.CAGR), "maxDD": rr(r.maxDD),
                 "avg_mom_weight": rr(r.avg_mom_weight, 3)} for r in sel.itertuples()]

    common = {
        "date": "2026-10-13",
        "data": ["Ken French Data Library (CRSP / Bloomberg, survivorship-free): F-F_Research_Data_Factors, 6_Portfolios_ME_Prior_12_2, "
                 "Developed_3_Factors, Developed_6_Portfolios_ME_Prior_12_2 (value-weighted, USD, to 2026-08)",
                 "Yahoo adjusted closes VWRL.L and IWFM.L (GBP/GBX) 2014-11..2026-08 for the tradeable check"],
        "benchmark": "champion momentum_tilt_v1 proxy: 50% market + 50% large-cap top-30% momentum (BIG HiPRIOR), monthly rebalance",
        "costs": "OCF MKT 0.22%, MOM 0.30% p.a.; one-way trading MKT 0.10%, MOM 0.35% (incl. 0.15% FX), cash 0.05%; stress x3",
        "in_sample": "US 1927-07..2000-12; Developed 1991-06..2005-12",
        "out_of_sample": "US 2001-01..2026-08; Developed 2006-01..2026-08",
        "robustness": ["costs x3", "neighbouring parameters", "3 sub-period regimes", "bootstrap P(>=50% drawdown in 10y)",
                       "deflated Sharpe of active return vs champion, across all configs of this run",
                       "tradeable ETF check with next-day execution (h01_tradeable.csv)"],
        "limitations": ["USD academic portfolios, not GBP; both arms share the currency so the comparison is fair, levels are not",
                        "BIG HiPRIOR is a proxy for MSCI World Momentum (different weighting and rebalance rules)",
                        "Monthly sampling; the one-day lag is tested only on the 2014-2026 ETF sample",
                        "An unpushed run on 2026-10-13 tried an unknown number of configs; they are not in the trial count"],
        "promoted": False,
        "evidence": ["research/h01_momentum_sleeve.py", "research/output/h01_gate.csv", "research/output/h01_all_configs.csv",
                     "research/output/h01_tradeable.csv"],
    }

    def decision(hyp):
        g = G[G.hypothesis == hyp]
        if g.PASS.all():
            return "SHADOW", "Passed every Stage 2 test in both markets; add as a shadow portfolio."
        failed = sorted({c[2:] for c in G.columns if c.startswith("t_") for row in g.itertuples() if not getattr(row, c)})
        detail = "Failed Stage 2: " + ", ".join(failed) + "."
        dd_cut = (g.maxDD - g.champ_maxDD)
        if (dd_cut >= 0.10).all():  # same label round 1 gave trend following: fails on return, cuts drawdowns a lot
            dd = "; ".join(f"{r.market} maxDD {r.maxDD:.1%} vs {r.champ_maxDD:.1%}, CAGR {r.dCAGR:+.2%}/yr" for r in g.itertuples())
            return "INSURANCE_ONLY", detail + " Not a return enhancer, but cuts out-of-sample drawdowns by 10pp+ in both markets (" + dd + ")."
        return "REJECTED", detail

    d6, dd6 = decision("P1")
    REG.joinpath("E006.json").write_text(json.dumps({
        "id": "E006", "title": "Volatility-managed momentum sleeve", "agenda_item": "P1",
        "hypothesis": "Scaling the momentum sleeve by the inverse of its 6-month relative volatility (clip 25-75%) beats a static 50/50.",
        "rationale": "Momentum crashes follow high momentum volatility (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016).",
        "methodology": "Pre-registered grid tv in {6,8,10}%, lookback 6m; pick by in-sample Sharpe; Stage 2 gate in both markets.",
        "results": block("P1"), "tradeable_check": tradeable("P1"),
        "trials": len(P1) * 2, "decision": d6, "decision_detail": dd6, **common}, indent=1) + "\n")
    d7, dd7 = decision("P2")
    REG.joinpath("E007.json").write_text(json.dumps({
        "id": "E007", "title": "Momentum sleeve with trend filter", "agenda_item": "P2",
        "hypothesis": "Moving the momentum sleeve to the market (or cash) when the market is below its 10-month SMA beats a static 50/50.",
        "rationale": "Momentum crashes happen in rebounds after bear markets; a trend filter on the market flags those states.",
        "methodology": "Variants to_mkt / to_cash at SMA10, pick by in-sample Sharpe; SMA 8 and 12 as neighbours; Stage 2 gate in both markets.",
        "results": block("P2"), "tradeable_check": tradeable("P2"),
        "trials": (len(P2) + len(NEIGH)) * 2, "decision": d7, "decision_detail": dd7, **common}, indent=1) + "\n")


if __name__ == "__main__":
    main()
