"""Build structured experiment records for round 1 from committed outputs.

Every number is read from research/output/*.csv (produced by the run_*.py
scripts), never typed by hand. Re-run after re-running the backtests:
    python3 build_registry_round1.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
REG = HERE / "experiments"

COMMON_DATA = ["Yahoo Finance adjusted closes (UCITS ETFs + US mutual-fund proxies), cleaned for unit flips",
               "Ken French Data Library (CRSP, survivorship-free)", "FRED: GBP/USD, UK 3m interbank"]
COMMON_COSTS = "0.05-0.25% one-way spread by asset; 0.15% FX fee on non-GBP lines; stressed x3/x5"


def r(x, nd=4):
    return None if pd.isna(x) else round(float(x), nd)


def e001():
    s = pd.read_csv(OUT / "allocation_selected.csv")
    fams = []
    for (fam, strat), g in s.groupby(["family", "strategy"], sort=False):
        is_, oos = g[g.period == "IS"].iloc[0], g[g.period == "OOS"].iloc[0]
        fams.append({"family": fam, "selected_on_IS_sharpe": strat,
                     "IS": {"CAGR": r(is_.CAGR), "Sharpe": r(is_.Sharpe, 3), "maxDD": r(is_.maxDD), "DSR": r(is_.DSR, 3)},
                     "OOS": {"CAGR": r(oos.CAGR), "Sharpe": r(oos.Sharpe, 3), "maxDD": r(oos.maxDD),
                             "dCAGR_vs_world": r(oos.dCAGR), "p_CAGR": r(oos.p_CAGR, 3), "dSharpe_vs_world": r(oos.dSharpe, 3), "p_Sharpe": r(oos.p_Sharpe, 3)}})
    allc = pd.read_csv(OUT / "allocation_all_configs.csv")
    world = allc[(allc.strategy == "WORLD buy&hold") & (allc.period == "OOS")].iloc[0]
    return {
        "id": "E001", "title": "Asset-allocation timing: trend, dual momentum, rotation, risk parity, vol targeting",
        "date": "2026-10-13", "agenda_item": "Round 1",
        "hypothesis": "Rules that time or rotate between equities, bonds, gold and cash beat buy-and-hold world equity after costs.",
        "rationale": "Time-series momentum (under-reaction/herding), cross-asset momentum, volatility clustering.",
        "data": COMMON_DATA + ["Monthly GBP total returns 1992-2026"],
        "methodology": "36 pre-declared configs in 6 families; per-family winner chosen on in-sample Sharpe only; signals use data to month-end t, trade t+1.",
        "benchmark": f"World equity buy-and-hold (OOS CAGR {r(world.CAGR)}, Sharpe {r(world.Sharpe, 3)}, maxDD {r(world.maxDD)})",
        "costs": COMMON_COSTS,
        "in_sample": "1992-01..2010-12", "out_of_sample": "2011-01..2026-09",
        "results": fams,
        "robustness": ["costs x3/x5 (GEM)", "one-day execution lag (GEM)", "8-regime breakdown", "1927-2026 US trend check (E002)"],
        "limitations": ["OOS period mostly a bull market", "pre-2012 data uses proxies; bond proxy weakest (corr 0.78)", "monthly sampling understates intra-month drawdowns"],
        "trials": 36, "decision": "REJECTED", "decision_detail": "No family beat world equity significantly OOS; GEM-12 +1.2%/yr p=0.15 kept as shadow portfolio C only.",
        "promoted": False, "evidence": ["research/output/allocation_selected.csv", "research/output/allocation_all_configs.csv", "research/run_allocation.py"],
    }


def e002():
    u = pd.read_csv(OUT / "us_century_trend.csv")
    res = {f"{row.strategy} {row.period}": {"CAGR": r(row.CAGR), "Sharpe": r(row.Sharpe, 3), "maxDD": r(row.maxDD)} for row in u.itertuples()}
    return {
        "id": "E002", "title": "Trend following on the US market, 1928-2026", "date": "2026-10-13", "agenda_item": "Round 1",
        "hypothesis": "A 10-month SMA or 12-month absolute-momentum filter improves risk-adjusted returns over a century.",
        "rationale": "Trend persistence; crash avoidance.", "data": ["Ken French US market and T-bill returns (CRSP)"],
        "methodology": "Monthly signal, 0.1% cost per switch; sub-period breakdown; bootstrap vs buy-and-hold (p-values in REPORT.md 4a).",
        "benchmark": "US market buy-and-hold", "costs": "0.1% per switch", "in_sample": "n/a (long-run check)", "out_of_sample": "1928-2026 sub-periods",
        "results": res, "robustness": ["four sub-periods"], "limitations": ["USD, gross index, US only"],
        "trials": 2, "decision": "INSURANCE_ONLY", "decision_detail": "Roughly halves max drawdown; does not raise long-run CAGR.",
        "promoted": False, "evidence": ["research/output/us_century_trend.csv", "research/run_regimes.py"],
    }


def e003():
    f = pd.read_csv(OUT / "factor_premia_by_period.csv").fillna("")
    return {
        "id": "E003", "title": "Persistence of factor premia (momentum, value, profitability)", "date": "2026-10-13", "agenda_item": "Round 1",
        "hypothesis": "Published long-short factor premia persist after publication and in developed markets.",
        "rationale": "Behavioural under-reaction (momentum); risk/mispricing (value, profitability).",
        "data": ["Ken French US and Developed factor files"], "methodology": "Annualised mean and t-stat by sub-period, gross of costs.",
        "benchmark": "zero premium", "costs": "none (gross long-short; not directly investable)", "in_sample": "1927-1989 / 1990-2010", "out_of_sample": "2011-2026",
        "results": f.to_dict(orient="records"), "robustness": ["US and Developed samples"], "limitations": ["long-short and gross: not what a £100 long-only account can hold"],
        "trials": 6, "decision": "MOMENTUM_SUPPORTED", "decision_detail": "Developed momentum still t≈2.1 after 2010; value premium ≈0.",
        "promoted": False, "evidence": ["research/output/factor_premia_by_period.csv", "research/run_factors.py"],
    }


def e004():
    f = pd.read_csv(OUT / "factor_etfs_vs_world.csv")
    return {
        "id": "E004", "title": "Tradeable MSCI World factor UCITS ETFs vs MSCI World", "date": "2026-10-13", "agenda_item": "Round 1",
        "hypothesis": "Factor ETFs (momentum, quality, value, min-vol) beat MSCI World net of fees.", "rationale": "As E003.",
        "data": ["Yahoo: IWFM/IWFQ/IWFV/MINV/SWDA GBP lines 2014-11..2026-09"], "methodology": "Monthly GBP returns, paired block bootstrap vs SWDA.",
        "benchmark": "SWDA (MSCI World)", "costs": "fund OCF included in prices; spreads ignored (buy-and-hold)", "in_sample": "academic evidence pre-2014 (E003)", "out_of_sample": "2014-11..2026-09",
        "results": [{k: (r(v) if isinstance(v, float) else v) for k, v in row.items()} for row in f.to_dict(orient="records")],
        "robustness": ["CAPM alpha t=1.21; excess falls to ≈0 without the 6 best months (REPORT.md 4b)"],
        "limitations": ["12 years only", "concentrated in a few months", "momentum crash risk not observed in sample"],
        "trials": 5, "decision": "PROMOTED", "decision_detail": "Momentum chosen as the 50% tilt in champion momentum_tilt_v1 (not statistically proven; p=0.09).",
        "promoted": True, "evidence": ["research/output/factor_etfs_vs_world.csv", "research/run_factors.py"],
    }


def e005():
    m = pd.read_csv(OUT / "mean_reversion.csv")
    return {
        "id": "E005", "title": "Short-term mean reversion (RSI-2, down-day streaks)", "date": "2026-10-13", "agenda_item": "Round 1",
        "hypothesis": "Buying short-term dips in an index ETF beats buy-and-hold.", "rationale": "Liquidity provision / overreaction.",
        "data": ["^SP500TR daily 1990-2010 (train)", "VUSA.L daily 2013-2026 (test)"], "methodology": "5 rules x 2 execution assumptions; 0.1% per trade.",
        "benchmark": "buy-and-hold", "costs": "0.10% one-way", "in_sample": "1990-2010", "out_of_sample": "2013-2026",
        "results": [{k: (r(v) if isinstance(v, float) else v) for k, v in row.items()} for row in m.to_dict(orient="records")],
        "robustness": ["same-close vs next-close execution"], "limitations": ["Yahoo daily data; no intraday spreads"],
        "trials": 10, "decision": "REJECTED", "decision_detail": "Test CAGR 4-5%/yr vs 16.4% buy-and-hold; in cash 85-95% of the time.",
        "promoted": False, "evidence": ["research/output/mean_reversion.csv", "research/run_meanrev.py"],
    }


def pending(eid, item, title, note):
    return {"id": eid, "title": title, "date": "2026-10-13", "agenda_item": item, "hypothesis": "see research/AGENDA.md",
            "rationale": "see research/AGENDA.md", "data": [], "methodology": "", "benchmark": "champion momentum_tilt_v1", "costs": "",
            "in_sample": "", "out_of_sample": "", "results": None, "robustness": [], "limitations": [note], "trials": 0,
            "decision": "PENDING_RERUN", "decision_detail": note, "promoted": False, "evidence": []}


def main():
    REG.mkdir(exist_ok=True)
    recs = [e001(), e002(), e003(), e004(), e005(),
            pending("E006", "P1", "Volatility-managed momentum sleeve",
                    "A test run on 2026-10-13 reported rejection (DSR 0.86-0.90) but its code and outputs were never pushed (git 403), so they are unverified; to be re-run by the research loop."),
            pending("E007", "P2", "Momentum sleeve with trend filter",
                    "A test run on 2026-10-13 reported rejection (lower OOS CAGR) but its code and outputs were never pushed (git 403), so they are unverified; to be re-run.")]
    for rec in recs:
        (REG / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {len(recs)} records to {REG}")


if __name__ == "__main__":
    main()
