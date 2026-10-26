"""B3: reproduce the published Stage 2 large-cap top-quintile results through the new backtester.

The specification is frozen in docs/edge/B3_STAGE2_SPEC.md (committed before this ran). Every input is cut at
2022-12-31 straight after reading, before any feature, return or score exists; the original `xsection.load` and
Stage 2 feature code then run on the cut copies.

    python3 edge_b3_reproduce.py   ->  equity/reports/research/edge/b3_reproduction.{md,json,csv}
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import data_sources
import edge_backtest as bt
import edge_exec_prices
import edge_registry
import edge_rules
import edge_split
import stage2
import xsection

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "equity" / "reports" / "research" / "edge"
PUBLISHED = ROOT.parent / "equity" / "reports" / "research" / "stage2_signals.json"
CUT = edge_split.EXPLORATION_LAST_OUTCOME
TOL = 1e-6
FIELDS = ["months", "avg_names", "mean_ic", "q5_minus_univ_ann_gross", "q5_minus_univ_ann_net", "q5_turnover_monthly"]
FILES = ["monthly_metrics.csv.gz", "prices_monthly.csv.gz", "sec_companies.csv.gz", "insider_trades.csv.gz"]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _assert_cut(dates, what: str) -> None:
    d = pd.to_datetime(pd.Series(list(dates)), errors="coerce")
    if (d > CUT).any():
        raise edge_split.HoldoutViolation(f"{what}: a date after {CUT.date()}")


def load_cut(tmp: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(xsection frame, insider trades, FF3 factors, month-end prices), each cut at 2022-12-31 on read."""
    for name in ("monthly_metrics.csv.gz", "prices_monthly.csv.gz"):
        x = pd.read_csv(xsection.DATA / name, dtype={"cik": int})
        x = x[pd.to_datetime(x["month"]) <= CUT]
        _assert_cut(x["month"], name)
        x.to_csv(tmp / name, index=False)
    df = xsection.load(tmp)  # the original loader, on the cut copies
    # the prices behind Stage 2's ret_next: every USD month-end close, as xsection.load selects them (a company
    # can have a price in a month without a metrics row, so prices are not taken from the merged frame)
    p = pd.read_csv(tmp / "prices_monthly.csv.gz", dtype={"cik": int})
    p = p[p["currency"] == "USD"].sort_values(["cik", "month"]).drop_duplicates(["cik", "month"], keep="last")
    p["month"] = pd.to_datetime(p["month"])
    _assert_cut(df["month"], "panel")
    trades = pd.read_csv(xsection.DATA / "insider_trades.csv.gz")
    trades = trades[pd.to_datetime(trades["filed"]) <= CUT]
    _assert_cut(trades["filed"], "insider trades")
    ff3 = edge_split.cut_series(data_sources.french("F-F_Research_Data_Factors"))
    _assert_cut(ff3.index, "FF3")
    return df, trades, ff3, p


def features(df, trades, ff3, months) -> pd.DataFrame:
    """stage2.build_features, step for step, with the cut inputs."""
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", dtype={"cik": int, "sic": str})
    df = stage2.prepare(df, comp)
    df["s6c_resid_mom"] = stage2.residual_momentum(df, ff3)
    df = df.join(stage2.insider_features(df, trades))
    df["s9_expectations_gap"] = stage2.expectations_gap(df, months)
    return df


def scored(df: pd.DataFrame, tid: str) -> pd.DataFrame:
    """Stage 2's large-band investable rows with the trial's score, in the harness's row order."""
    fn = stage2.TRIALS[tid][2]
    d = xsection.investable(df[(df["month"] >= stage2.START) & (df["month"] <= stage2.END)]).copy()
    d["score"] = np.nan
    for _, g in d.groupby("month"):
        d.loc[g.index, "score"] = fn(g)
    return d


def engine_panel(d: pd.DataFrame) -> pd.DataFrame:
    p = d[["cik", "month", "score", "band", "close_raw", "group"]].copy()
    p["quality_ok"] = True  # Stage 2 had no quality exclusion
    return p


def stage2_series(r: pd.DataFrame) -> pd.DataFrame:
    return r.set_index("month")[["q5_minus_univ", "q5_turnover", "q5_net"]]


def engine_series(q5: bt.Result, univ: bt.Result, months) -> pd.DataFrame:
    """Per decision month: top-quintile and universe returns over the following period, name turnover (Stage 2's
    definition, from the engine's holdings) and Stage 2's cost applied to it."""
    rows, prev = [], set()
    nq, nu = q5.nav_usd, univ.nav_usd
    for m in months:  # Stage 2's months only (it skipped any month with fewer than 30 names)
        e = m + pd.offsets.MonthEnd(1)
        names = set(q5.holdings[m])
        turn = 1.0 if not prev else len(names - prev) / max(len(names), 1)
        prev = names
        rq = nq.loc[e] / nq.loc[m] - 1
        ru = nu.loc[e] / nu.loc[m] - 1
        rows.append({"month": m, "q5": rq, "univ": ru, "q5_minus_univ": rq - ru, "q5_turnover": turn,
                     "q5_net": rq - ru - 2 * xsection.COST_PER_TURNOVER * turn, "n_q5": len(names)})
    return pd.DataFrame(rows).set_index("month")


def repro_prices(d: pd.DataFrame) -> pd.DataFrame:
    """Month-end adjclose of every company the panel can hold, decisions and the month after, in the B1 schema."""
    p = d[["cik", "month", "adjclose"]].rename(columns={"adjclose": "me_adjclose"})
    p = p[p["month"] <= CUT].assign(status="ok")
    p["exec_date"] = p["month"]
    return p


def nextday_panel(df: pd.DataFrame, tid: str) -> pd.DataFrame:
    """Section 4: the same score, but the universe does not require a known next-month return."""
    fn = stage2.TRIALS[tid][2]
    d = df[(df["month"] >= stage2.START) & (df["month"] <= stage2.END)]
    d = d[(d["close_raw"] >= xsection.MIN_PRICE) & d["band"].notna()].copy()
    d["score"] = np.nan
    for _, g in d.groupby("month"):
        d.loc[g.index, "score"] = fn(g)
    return engine_panel(d[d["band"] == "large"])


def run() -> dict:
    hashes = {f: sha(xsection.DATA / f) for f in FILES}
    hashes["F-F_Research_Data_Factors.csv"] = sha(data_sources.DATA / "french" / "F-F_Research_Data_Factors.csv")
    edge_registry.require("B3-REPRO-STAGE2")
    edge_registry.require("B3-NEXTDAY-STAGE2")
    published = json.loads(PUBLISHED.read_text())
    with tempfile.TemporaryDirectory() as t:
        df, trades, ff3, prices = load_cut(Path(t))
    months_all = sorted(df.loc[(df["month"] >= stage2.START) & (df["month"] <= stage2.END), "month"].unique())
    df = features(df, trades, ff3, months_all)
    fx = pd.Series(1.0, index=pd.bdate_range("2014-12-01", CUT))  # USD throughout, as Stage 2
    ex = edge_exec_prices.load()
    hashes["exec_prices_to_2022.csv.gz"] = edge_exec_prices._sha(edge_exec_prices.OUT_DIR / "exec_prices_to_2022.csv.gz")
    prices_rep = repro_prices(prices[prices["adjclose"].notna()])
    cfg_q = bt.Config(n=0, rebalance_every=1, buffer=1.0, sector_cap=0, bands=("large",), cost_mult=0.0,
                      convention=bt.REPRO_CONVENTION, selection="stage2_top_quintile")
    cfg_u = bt.Config(**{**cfg_q.__dict__, "select_all": True})
    out, monthly = {}, []
    for tid in stage2.TRIALS:
        d = scored(df, tid)
        orig = xsection.evaluate(d.drop(columns="score"), stage2.TRIALS[tid][2], tid, start=stage2.START,
                                 end=stage2.END, bands=("large",))
        ob, pb = orig["bands"]["large"], published[tid]["bands"]["large"]
        cmp1 = {f: {"published": pb[f], "rerun": ob[f], "diff": ob[f] - pb[f]} for f in FIELDS}
        s_orig = stage2_series(orig["series"]["large"])
        months = list(s_orig.index)
        panel = engine_panel(d[d["band"] == "large"])  # scores were computed on all bands, as in Stage 2
        ids = set(panel["cik"])
        pr = prices_rep[prices_rep["cik"].isin(ids)]
        rq = bt.run(panel, pr, fx, cfg_q, start=months[0], end=months[-1] + pd.offsets.MonthEnd(1))
        ru = bt.run(panel, pr, fx, cfg_u, start=months[0], end=months[-1] + pd.offsets.MonthEnd(1))
        s_eng = engine_series(rq, ru, months)
        # Stage 2's top quintile, recomputed, for the holdings check
        hold_diff = {}
        for m, g in d[d["band"] == "large"].dropna(subset=["score"]).groupby("month"):
            if m not in s_orig.index:  # a month Stage 2 skipped (< 30 names) is not compared
                continue
            s2 = set(g.loc[pd.qcut(g["score"].rank(method="first"), 10, labels=False) >= 8, "cik"])
            x = sorted(int(c) for c in s2 ^ set(rq.holdings[m]))
            if x:
                hold_diff[m.strftime("%Y-%m")] = x
        same_sets = not hold_diff
        # company-months in the universe whose decision or next-month adjusted close is <= 0
        nxt = d[["cik", "month"]].assign(month=d["month"] + pd.offsets.MonthEnd(1)).merge(
            prices[["cik", "month", "adjclose"]], on=["cik", "month"], how="left")["adjclose"].to_numpy()
        lg = (d["band"] == "large").to_numpy() & d["score"].notna().to_numpy()
        np_rows = d[lg & ((d["adjclose"] <= 0).to_numpy() | (nxt <= 0))]
        np_months = sorted(set(np_rows["month"]))
        diff = (s_eng[["q5_minus_univ", "q5_turnover", "q5_net"]] - s_orig).abs()
        clean = diff.drop(index=[m for m in np_months if m in diff.index])
        ann = {"rerun_q5_net_ann": float(s_orig["q5_net"].mean() * 12),
               "engine_q5_net_ann": float(s_eng["q5_net"].mean() * 12)}
        ann["diff"] = ann["engine_q5_net_ann"] - ann["rerun_q5_net_ann"]
        pass1 = cmp1["months"]["diff"] == 0 and all(abs(v["diff"]) <= TOL for v in cmp1.values())
        pass2 = bool(diff.max().max() <= TOL and abs(ann["diff"]) <= TOL and same_sets)
        # Section 4: next-day execution, no look-ahead universe, native costs
        pn = nextday_panel(df, tid)
        ex_t = ex[ex["cik"].isin(set(pn["cik"]))]
        cfg_nq = bt.Config(n=0, rebalance_every=1, buffer=1.0, sector_cap=0, bands=("large",), cost_mult=1.0,
                           selection="stage2_top_quintile")
        cfg_nu = bt.Config(**{**cfg_nq.__dict__, "select_all": True, "cost_mult": 0.0})
        nq = bt.run(pn, ex_t, fx, cfg_nq, start=stage2.START, end=stage2.END)
        nu = bt.run(pn, ex_t, fx, cfg_nu, start=stage2.START, end=stage2.END)
        dq, du = nq.nav_usd, nu.nav_usd  # indexed by trade date; the period after decision m ends at the next one
        td = pd.Series(dq.index, index=sorted(nq.holdings))
        nd = pd.Series({m: (dq.iloc[k + 1] / dq.iloc[k]) - (du.iloc[k + 1] / du.iloc[k])
                        for k, m in enumerate(td.index[:-1]) if m in s_orig.index})
        n_months = len(nd)
        common = s_orig["q5_net"].loc[nd.index]
        out[tid] = {"desc": stage2.TRIALS[tid][1], "published_vs_rerun": cmp1, "pass_published_vs_rerun": pass1,
                    "engine_vs_rerun_max_abs_monthly": {c: float(v) for c, v in diff.max().items()},
                    "engine_vs_rerun_annual": ann, "same_holdings": same_sets, "pass_engine_vs_rerun": pass2,
                    "holdings_differ": hold_diff,
                    "nonpositive_price_rows": [(int(c), str(t), m.strftime("%Y-%m")) for c, t, m in
                                               zip(np_rows["cik"], np_rows["ticker"], np_rows["month"])],
                    "months_over_tol": [m.strftime("%Y-%m") for m in diff.index[diff.max(axis=1) > TOL]],
                    "max_abs_monthly_outside_nonpositive_months": float(clean.max().max()),
                    "months": len(months), "engine_missing_exits": sum(e["event"] == "exit" for e in rq.log + ru.log),
                    "nextday": {"months": n_months, "q5_net_ann": float(nd.mean() * 12),
                                "stage2_same_months_ann": float(common.mean() * 12),
                                "diff": float(nd.mean() * 12 - common.mean() * 12),
                                "turnover_weight_monthly": float(np.mean(list(nq.turnover.values()))),
                                "missing_exits": sum(e["event"] == "exit" for e in nq.log),
                                "skipped_entries": sum(e["event"] == "skipped_entry" for e in nq.log)}}
        monthly.append(s_orig.add_prefix("stage2_").join(s_eng.add_prefix("engine_")).assign(trial=tid))
        print(tid, "pass" if pass1 and pass2 else "FAIL", f"{ann['diff']:+.2e}", flush=True)
    return {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hashes": hashes,
            "trials": out, "monthly": pd.concat(monthly).reset_index()}


def report(res: dict) -> str:
    T = res["trials"]
    ok = all(t["pass_published_vs_rerun"] and t["pass_engine_vs_rerun"] for t in T.values())
    L = [f"Run {res['run_utc']}. Specification frozen before the run: `docs/edge/B3_STAGE2_SPEC.md` (commit 223e826). "
         "Data cut at 2022-12-31 on read; no holdout price, signal or outcome was read.", "",
         f"## Result: reproduction {'**PASSES**' if ok else '**FAILS** the 1e-6 tolerance'}: "
         f"{sum(t['pass_published_vs_rerun'] and t['pass_engine_vs_rerun'] for t in T.values())} of {len(T)} trials "
         "pass both comparisons (cause and detail under Investigation below)", "",
         "### A. Original Stage 2 code on cut data vs the published result (top quintile, large caps, net, a year)", "",
         "| Trial | Published | Rerun | Difference | All 6 fields within 1e-6 |", "|---|---:|---:|---:|---|"]
    for k, t in T.items():
        c = t["published_vs_rerun"]["q5_minus_univ_ann_net"]
        L.append(f"| {k} | {c['published']:+.6%} | {c['rerun']:+.6%} | {c['diff']:+.2e} | "
                 f"{'yes' if t['pass_published_vs_rerun'] else 'NO'} |")
    L += ["", "### B. New engine vs original code, same assumptions", "",
          "| Trial | Months | Stage 2 net, a year | Engine net, a year | Difference | Largest monthly difference | "
          "Months over 1e-6 | Largest difference in all other months | Holdings differ in | Pass |",
          "|---|---:|---:|---:|---:|---:|---|---:|---|---|"]
    for k, t in T.items():
        a = t["engine_vs_rerun_annual"]
        L.append(f"| {k} | {t['months']} | {a['rerun_q5_net_ann']:+.6%} | {a['engine_q5_net_ann']:+.6%} | "
                 f"{a['diff']:+.2e} | {max(t['engine_vs_rerun_max_abs_monthly'].values()):.2e} | "
                 f"{', '.join(t['months_over_tol']) or 'none'} | {t['max_abs_monthly_outside_nonpositive_months']:.1e} | "
                 f"{', '.join(t['holdings_differ']) or 'none'} | {'yes' if t['pass_engine_vs_rerun'] else 'NO'} |")
    rows = sorted({tuple(x) for t in T.values() for x in t["nonpositive_price_rows"]}, key=lambda x: x[2])
    L += ["", "Universe company-months with an adjusted close at or below zero at the decision or the next month-end "
          "(Stage 2 computed a return from them; the engine refuses a price <= 0): "
          + ("; ".join(f"{t} (CIK {c}) {m}" for c, t, m in rows) or "none") + "."]
    L += ["", "### C. Separate comparison: next-day execution (not a reproduction)", "",
          "Same scores and top-quintile rule. Trades at the next NYSE day's close (B1), no look-ahead universe, "
          "a held name losing its price exits at -30%, costs on weight changes (0.30% a unit). Decisions 2015-01 to "
          "2022-10: the 2022-11 decision's next-day period would end in January 2023, which is holdout.", "",
          "| Trial | Months | Stage 2 net, a year (same months) | Next-day net, a year | Difference | "
          "Weight turnover a month | Missing-price exits | Skipped entries |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k, t in T.items():
        n = t["nextday"]
        L.append(f"| {k} | {n['months']} | {n['stage2_same_months_ann']:+.2%} | {n['q5_net_ann']:+.2%} | "
                 f"{n['diff']:+.2%} | {n['turnover_weight_monthly']:.1%} | {n['missing_exits']} | "
                 f"{n['skipped_entries']} |")
    L += ["", "## Data files and hashes", "", "| File | sha256 |", "|---|---|"]
    L += [f"| {f} | `{h}` |" for f, h in res["hashes"].items()]
    return "\n".join(L) + "\n"


def main() -> None:
    res = run()
    OUT.mkdir(parents=True, exist_ok=True)
    res["monthly"].to_csv(OUT / "b3_reproduction_monthly.csv", index=False)
    (OUT / "b3_reproduction.json").write_text(json.dumps({k: v for k, v in res.items() if k != "monthly"},
                                                          indent=1, default=str))
    text = bt.report("B3: Stage 2 reproduction through the new backtester", {}, report(res) + "\n" + NOTES)
    (OUT / "b3_reproduction.md").write_text(edge_rules.require_disclosure(text))
    print(OUT / "b3_reproduction.md")


NOTES = """## Investigation and verdict

- **Comparison A passes for all 15 trials.** Stage 2's own code, rerun now on data cut at 2022-12-31, matches
  the published result. All six summary fields agree within 1e-6, and the month counts are equal. So the
  published Stage 2 numbers did not depend on any holdout row. The Ken French factor file was re-downloaded
  after Stage 2 ran, but this made no measurable difference to S6c.
- **Comparison B (engine vs Stage 2 code) misses the 1e-6 tolerance for 12 of 15 trials, in 4 months only:**
  2022-07, 2022-08, 2022-10 and 2022-11.
  - Cause: New Fortress Energy (NFE) has a negative dividend-adjusted close in the research dataset in those
    months. This is a data defect recorded in Phase A.
  - Stage 2's harness computed a return from two negative prices and kept NFE in the universe and, for some
    trials, in the top quintile.
  - The new engine refuses any price at or below zero, by design (`edge_rules.holding_return`), so NFE cannot
    be bought there.
  - In every other month and every trial, engine and Stage 2 agree to within 1e-15.
  - Where holdings differ at all, the only difference is NFE in those months. In the other failing trials, NFE
    was in the universe but not in the top quintile.
  - S4, S7a and S9 pass outright because NFE has no score for them in those months.
- **Not changed to obtain a pass.** Making them agree would mean one of two things:
  - letting the engine trade at negative prices, which removes a safety rule;
  - excluding NFE from the Stage 2 reproduction, which changes the frozen specification.

  Either is a methodology decision for the owner.
- **Effect:** at most 0.021 percentage points a year on any trial's annualised top-quintile result.
- **Two harness corrections made during the investigation.** Both bring the inputs to the frozen
  specification; neither is a parameter change.
  1. The engine's month-end prices were first taken from the merged metrics-and-prices frame. That frame
     lacks one month (CIK 1635327, 2021-06) for which `prices_monthly` has a price and Stage 2 has a return.
     They are now taken from `prices_monthly` directly, as Stage 2's `ret_next` is.
  2. S4 has months with fewer than 30 scored large caps, which Stage 2 skipped. The engine raised an error
     there. It now holds nothing in such a month, and the month is left out of the comparison, as Stage 2
     left it out of its series.
- **Comparison C (next-day execution) is descriptive and was registered beforehand.**
  - Trading at the next day's close, with no look-ahead universe and costs on weight changes, moves the
    top-quintile result by between −0.72 and +0.31 points a year.
  - Every trial that was negative stays negative. S5a stays the only positive one (+0.55% a year, net).
  - No missing-price exit occurred. 0 to 13 entries a trial were skipped for lack of an execution price.

## Limitations (beyond the standing list above)

- **Survivorship bias.** Companies that stopped trading before 2026 have no free price, so they are never in
  the universe. Every Stage 2 and engine number shares this bias. B3 tests the arithmetic, not the data.
- **Look-ahead in the original specification.** Stage 2's universe requires a known next-month return. The
  reproduction keeps this deliberately, and comparison C removes it.
- **Execution at the decision close** (Stage 2) is not achievable in practice; comparison C shows the next-day
  alternative.
- **FX.** B3 is in USD, as Stage 2 was, so no FX is used. For later GBP work, FRED is unreachable and all FX
  comes from Yahoo GBPUSD=X.
- **Benchmark.** The comparison leg is the equal-weighted large-cap universe, as in Stage 2, not VWRP.
- **Data defects** (negative adjusted prices; share-count scaling) remain in the research dataset. The engine
  guards against the first; the Phase A quality rule handles the second for new trials, but is off here
  because Stage 2 did not use it.
- **Holdout and scope.** No 2023 or later price, signal or outcome was read. No new signal was registered or
  run. No confirmation test, demo allocation or account change was made.
"""

if __name__ == "__main__":
    main()
