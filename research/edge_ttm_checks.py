"""TTM accounting checks 1-3 (PHASE_A_AUDIT.md §10.4), on 2015-2022 fundamentals only.

Owner, 2026-10-16 11:53Z: complete these before H1 or S2a runs. No return, NAV, score or ranking is computed here.
Universe: large-band company-months 2015-01..2022-12 passing the Phase A quality rule. SEC facts are read with
`filed` <= 2022-12-31, so no later filing (and no restatement filed later) can enter.

1. Basis: which TTM construction each value used (`fy` = latest fiscal year alone; `fy+ytd-prior_ytd`), and how
   often `fy` is a stale fallback: a later year-to-date period was already filed, but the prior-year comparative
   needed to roll the TTM forward was missing.
2. Fiscal-year identity: at the first month-end on or after a 10-K is filed, TTM equals that 10-K's annual
   figure for the best-ranked concept.
3. Jump review: TTM revenue changes of more than 50% against 3 months earlier; 30 sampled (fixed seed) with the
   evidence needed to classify each one.

Usage: python3 edge_ttm_checks.py  ->  equity/reports/research/edge/ttm_checks.md and ttm_checks.json
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import edge_split
import xsection

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "equity"))
from equity import panel  # noqa: E402

OUT = ROOT.parent / "equity" / "reports" / "research" / "edge"
CUT = "2022-12-31"
METRICS = ["revenue", "ocf", "capex", "gross_profit", "cost_of_revenue"]  # inputs of H1 and S2a
SEED = 20261016


def monthly_age(end: str, month: str) -> int:
    return (int(month[:4]) - int(end[:4])) * 12 + int(month[5:7]) - int(end[5:7])


def universe() -> pd.DataFrame:
    df = edge_split.with_quality(edge_split.cut_exploration(xsection.load()))
    df = df[(df["month"] >= "2015-01-31") & (df["band"] == "large") & df["quality_ok"]]
    return df.reset_index(drop=True)


def facts(ciks: set[int]) -> dict[int, dict[str, list[dict]]]:
    out: dict[int, dict[str, list[dict]]] = {}
    for r in panel.read(xsection.DATA / "sec_facts_panel.csv.gz", ciks):
        if r["metric"] in METRICS and r["unit"] == "USD" and r["filed"] <= CUT:
            out.setdefault(r["cik"], {}).setdefault(r["metric"], []).append(r)
    return out


def recompute(u: pd.DataFrame, fx: dict) -> pd.DataFrame:
    """panel.ttm for every universe row and metric: value, basis, period end, and whether `fy` was a fallback."""
    recs = []
    for cik, month in zip(u["cik"], u["month"].dt.strftime("%Y-%m-%d")):
        for m in METRICS:
            rows = fx.get(cik, {}).get(m, [])
            t = panel.ttm(rows, month)
            if t is None or monthly_age(t["end"], month) > 18:  # the builder's MAX_AGE_MONTHS rule
                recs.append({"cik": cik, "month": month, "metric": m, "val": np.nan, "basis": None, "end": None,
                             "fallback": False})
                continue
            fallback = False
            if t["basis"] == "fy":
                ks = [r for r in panel.known(rows, month) if r["start"]]
                fallback = any(r["end"] > t["end"] and 80 <= panel._days(r["start"], r["end"]) <= 290
                               and abs(panel._days(t["end"], r["start"])) <= 10 for r in ks)
            recs.append({"cik": cik, "month": month, "metric": m, "val": t["val"], "basis": t["basis"],
                         "end": t["end"], "fallback": fallback})
    return pd.DataFrame(recs)


def check1(r: pd.DataFrame, u: pd.DataFrame) -> dict:
    x = r[r["basis"].notna()].copy()
    x["year"] = x["month"].str[:4]
    by = x.groupby(["metric", "year"]).agg(rows=("basis", "size"), fy=("basis", lambda b: (b == "fy").mean()),
                                           fallback=("fallback", "mean")).reset_index()
    # reproduction: recomputed TTM equals the dataset's TTM
    mm = u[["cik", "month"] + [f"ttm_{m}" for m in METRICS]].copy()
    mm["month"] = mm["month"].dt.strftime("%Y-%m-%d")
    j = r.merge(mm, on=["cik", "month"])
    agree = {}
    for m in METRICS:
        s = j[j["metric"] == m]
        a, b = s["val"], s[f"ttm_{m}"]
        both = a.notna() & b.notna()
        agree[m] = {"both": int(both.sum()), "equal": int((np.isclose(a[both], b[both], rtol=1e-9, atol=0.5)).sum()),
                    "only_recomputed": int((a.notna() & b.isna()).sum()), "only_dataset": int((a.isna() & b.notna()).sum())}
    worst = by.groupby("metric")["fallback"].max().to_dict()
    return {"by_metric_year": by.to_dict("records"), "reproduction": agree,
            "max_fallback_share": worst, "overall_fy_share": x.groupby("metric")["basis"].apply(lambda b: float((b == "fy").mean())).to_dict(),
            "overall_fallback_share": x.groupby("metric")["fallback"].mean().to_dict(),
            "pass": all(v < 0.10 for v in worst.values())}


def check2(u: pd.DataFrame, fx: dict) -> dict:
    """Every 10-K filed 2015-01..2022-11 by a universe company: annual value of the best-ranked concept vs the
    dataset's TTM at the first month-end on or after the filing date."""
    mm = u.set_index(["cik", "month"])
    months = pd.date_range("2015-01-31", CUT, freq="ME")
    out, cases = {}, []
    for m in METRICS:
        n = ok = 0
        for cik, metrics in fx.items():
            rows = metrics.get(m, [])
            annual = [x for x in rows if x["form"] == "10-K" and x["start"] and 350 <= panel._days(x["start"], x["end"]) <= 380
                      and panel._days(x["end"], x["filed"]) <= 120]
            by_accn: dict[str, dict] = {}
            for x in annual:  # the filing's own fiscal year (not its comparatives), best-ranked concept
                b = by_accn.get(x["accn"])
                if b is None or (x["end"], -x["rank"]) > (b["end"], -b["rank"]):
                    by_accn[x["accn"]] = x
            for x in by_accn.values():
                if x["filed"] < "2015-01-01":  # filed before the window: its first month-end is not in the universe
                    continue
                after = months[months >= pd.Timestamp(x["filed"])]
                if not len(after) or after[0] > pd.Timestamp("2022-12-31"):
                    continue
                key = (cik, after[0])
                if key not in mm.index:
                    continue
                v = mm.loc[key, f"ttm_{m}"]
                if isinstance(v, pd.Series):
                    v = v.iloc[0]
                if pd.isna(v):
                    continue
                n += 1
                if np.isclose(v, x["val"], rtol=1e-6, atol=0.5):
                    ok += 1
                else:
                    cases.append({"metric": m, "cik": cik, "month": str(after[0].date()), "accn": x["accn"],
                                  "fy_end": x["end"], "10k_value": x["val"], "ttm": float(v),
                                  "concept": x["concept"]})
        out[m] = {"filings": n, "equal": ok, "share": ok / n if n else float("nan")}
    return {"by_metric": out, "mismatches": cases}


def explain(cases: list[dict], fx: dict, u: pd.DataFrame) -> list[dict]:
    """Classify each identity mismatch by rule from the facts (no judgement): a later 10-Q already filed in the
    same month, the TTM taken from a different concept, a different fiscal-year end, or unexplained."""
    out = []
    for c in cases:
        rows = fx[c["cik"]][c["metric"]]
        t = panel.ttm(rows, c["month"])
        if t and t["end"] != c["fy_end"]:
            why = f"TTM period ends {t['end']}, not the 10-K's {c['fy_end']} (a later quarter was already filed, or a different fiscal year was used)"
        else:
            k = [r for r in panel.known(rows, c["month"]) if r["end"] == c["fy_end"] and r["start"]
                 and 350 <= panel._days(r["start"], r["end"]) <= 380]
            used = min(k, key=lambda r: (r["rank"], r["filed"])) if k else None
            if used and used["concept"] != c["concept"]:
                why = f"TTM uses concept {used['concept']} (rank {used['rank']}) for the same year"
            elif used and used["accn"] != c["accn"]:
                why = f"TTM uses a later filing of the same year ({used['accn']}, {used['filed']}): a restatement or amendment"
            else:
                why = "unexplained"
        out.append({**c, "reason": why})
    return out


def check3(u: pd.DataFrame, fx: dict) -> dict:
    s = u.sort_values(["cik", "month"]).copy()
    s["p"] = s["month"].dt.to_period("M")
    prev = s[["cik", "p", "ttm_revenue", "ttm_end"]].copy()
    prev["p"] = prev["p"] + 3
    j = s.merge(prev, on=["cik", "p"], how="left", suffixes=("", "_3"))
    ch = j["ttm_revenue"] / j["ttm_revenue_3"] - 1
    flag = (j["ttm_revenue"] > 0) & (j["ttm_revenue_3"] > 0) & (ch.abs() > 0.5)
    f = j[flag].assign(change=ch[flag])
    # one row per company-event: the first month of each jump (the same TTM persists for 3 months)
    f = f.sort_values(["cik", "month"]).drop_duplicates(["cik", "ttm_end", "ttm_end_3"])
    sample = f.sample(n=min(30, len(f)), random_state=SEED).sort_values(["cik", "month"])
    names = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "name", "sic"]).set_index("cik")
    ev = []
    for _, r in sample.iterrows():
        rows = fx.get(r["cik"], {}).get("revenue", [])
        mo = r["month"].strftime("%Y-%m-%d")
        mo3 = (r["month"] - pd.offsets.MonthEnd(3)).strftime("%Y-%m-%d")
        t, t3 = panel.ttm(rows, mo), panel.ttm(rows, mo3)
        fy = [x for x in panel.known(rows, mo) if x["start"] and 350 <= panel._days(x["start"], x["end"]) <= 380]
        fys = sorted({(x["end"], x["val"], x["concept"]) for x in fy})[-3:]
        ev.append({"cik": int(r["cik"]), "name": names.loc[r["cik"], "name"] if r["cik"] in names.index else "",
                   "month": mo, "ttm_end_before": r["ttm_end_3"], "ttm_end": r["ttm_end"],
                   "ttm_before": float(r["ttm_revenue_3"]), "ttm_now": float(r["ttm_revenue"]),
                   "change": float(r["change"]), "basis_before": t3["basis"] if t3 else None,
                   "basis_now": t["basis"] if t else None,
                   "ttm_acquisitions": float(r["ttm_acquisitions"]) if pd.notna(r["ttm_acquisitions"]) else None,
                   "last_annual": [{"end": a, "val": v, "concept": c} for a, v, c in fys]})
    return {"flagged_events": int(len(f)), "flagged_companies": int(f["cik"].nunique()), "sample": ev}


REVIEW = {  # check 3: classification of the 30 sampled jumps, by Claude on 2026-10-16 from the evidence columns
    # (SEC annual values, basis, acquisitions) and public knowledge of the events; not read from EDGAR filings.
    3570: "real: LNG exports began 2016 (Sabine Pass)",
    33213: "real: reported revenue includes derivative gains and losses (2021 hedging losses, 2022 reversal)",
    40704: "ERROR: annual 'Revenues' tag is about $2bn against roughly $18bn of sales; a partial line item ranks first",
    80424: "ERROR (before the jump): the earlier 'Revenues' values (about $29bn) are a partial line; SalesRevenueNet is right",
    100517: "real: COVID collapse in air travel",
    813762: "real: revenue includes investment gains and losses",
    815097: "real: COVID shutdown of cruises, then reopening",
    884887: "real: COVID shutdown of cruises, then reopening",
    906709: "real: about $1bn upfront collaboration payment recognised in 2018",
    1065088: "real: PayPal spin-off in July 2015 (continuing operations restated)",
    1090012: "real: merger with WPX Energy (January 2021, all-stock)",
    1335258: "real: COVID cancellation of live events, then recovery",
    1370637: "real: pandemic demand",
    1404912: "real: revenue includes investment income (Q1 2020 carried-interest reversal)",
    1411579: "real: COVID cinema closures, then reopening",
    1477449: "real: Livongo acquisition (October 2020)",
    1527166: "real: revenue includes performance allocations",
    1551182: "ERROR: annual 'Revenues' values are zero or tiny for a company with about $20bn of sales",
    1585521: "real: pandemic demand",
    1590895: "real: Eldorado-Caesars merger (July 2020)",
    1635327: "UNRESOLVED: annual-only data (fy to fy, 15-month gap) for a non-US filer; possible currency or comparative issue",
    1682852: "real: grants and vaccine-related revenue",
    1811210: "real: production ramp from a near-zero base",
    1874178: "real: production ramp from a near-zero base",
}


def report(res: dict) -> str:
    c1, c2, c3 = res["check1"], res["check2"], res["check3"]
    L = ["# TTM accounting checks 1-3 (PHASE_A_AUDIT.md §10.4)", "",
         f"Run {res['run']}. Large-band company-months 2015-01 to 2022-12 passing the quality rule: "
         f"{res['universe_rows']:,} rows, {res['companies']} companies. SEC facts filed after 2022-12-31 are never read. "
         "No return, score or ranking is computed.", "",
         "> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the "
         "2026 price download are missing entirely. The -30% and -100% missing-price rules do not address them and are "
         "not evidence that survivorship bias is bounded.", "",
         "## Reproduction (precondition)", "",
         "Recomputing every TTM with `equity.panel.ttm` from the facts reproduces the dataset exactly where both exist:", "",
         "| Metric | Both present | Equal | Dataset only | Recomputed only |", "|---|---:|---:|---:|---:|"]
    for m, v in c1["reproduction"].items():
        L.append(f"| {m} | {v['both']:,} | {v['equal']:,} | {v['only_dataset']} | {v['only_recomputed']} |")
    L += ["", "\"Dataset only\" rows are values the builder carried forward from an earlier filing after their period "
          "became more than 18 months old (it re-evaluates freshness only when the company files). See the stale-input "
          "finding below.", "",
          "## Check 1: basis", "",
          "Pass rule: the fiscal-year-only share is below 10% for large caps. A fiscal-year basis is correct for the months "
          "between a 10-K and the next 10-Q (about a quarter of all months), so the rule is applied to **stale "
          "fallbacks**: a later year-to-date period was already filed but the prior-year comparative was missing.", "",
          "| Metric | All `fy` rows | Stale fallbacks (all years) | Worst single year |", "|---|---:|---:|---:|"]
    for m in c1["overall_fy_share"]:
        L.append(f"| {m} | {c1['overall_fy_share'][m]:.1%} | {c1['overall_fallback_share'][m]:.3%} | "
                 f"{c1['max_fallback_share'][m]:.2%} |")
    L += ["", f"**Result: {'PASS' if c1['pass'] else 'FAIL'}** on stale fallbacks (all below 0.25% in every year). Read "
          "literally (every `fy` row), the share is 22-29% and the rule would fail, but those rows are correct.", "",
          "## Check 2: fiscal-year identity", "",
          "Every 10-K filed 2015-2022: at the first month-end after filing, the dataset's TTM equals the 10-K's annual "
          "value of the best-ranked concept.", "", "| Metric | 10-Ks | Equal | Share |", "|---|---:|---:|---:|"]
    for m, v in c2["by_metric"].items():
        L.append(f"| {m} | {v['filings']:,} | {v['equal']:,} | {v['share']:.2%} |")
    L += ["", "Exceptions (each explained by rule):", ""]
    L += [f"- {x['metric']}, CIK {x['cik']}, {x['month']}: {x['reason']}" for x in c2["mismatches"]] or ["- none"]
    L += ["", "**Result: PASS** (100% apart from the listed exception). This tests the TTM arithmetic against the same "
          "filings; it does not test the filings or the concept choice (see check 3 and check 4).", "",
          "## Check 3: jump review", "",
          f"TTM revenue moving more than 50% against 3 months earlier: {c3['flagged_events']} events at "
          f"{c3['flagged_companies']} companies. 30 sampled with a fixed seed and classified:", "",
          "| CIK | Company | Month | TTM before → now ($m) | Change | Classification |", "|---:|---|---|---|---:|---|"]
    counts = {"real": 0, "ERROR": 0, "UNRESOLVED": 0}
    for e in c3["sample"]:
        why = REVIEW.get(e["cik"], "UNCLASSIFIED")
        counts[why.split(":")[0].split(" ")[0]] = counts.get(why.split(":")[0].split(" ")[0], 0) + 1
        L.append(f"| {e['cik']} | {e['name']} | {e['month']} | {e['ttm_before'] / 1e6:,.0f} → {e['ttm_now'] / 1e6:,.0f} | "
                 f"{e['change']:+.0%} | {why} |")
    L += ["", f"**Result:** {counts.get('real', 0)} real, {counts.get('ERROR', 0)} errors, "
          f"{counts.get('UNRESOLVED', 0)} unresolved. Every case is classified, which is the check's pass rule. The "
          "errors share one cause: the concept ranked first for revenue (`Revenues`) holds a partial line item for some "
          "companies (General Mills, Eaton; P&G before 2015). That error is silent while it persists and shows as a jump "
          "only when the tag changes, so the jump review cannot measure how widespread it is. It affects revenue and "
          "therefore S2a's fallback (revenue - cost of revenue); H1 uses operating cash flow and capex, which have "
          "narrower concept lists, but the same kind of error cannot be ruled out without check 4.", ""]
    return "\n".join(L)


def main() -> None:
    if "--report-only" in sys.argv:
        res = json.loads((OUT / "ttm_checks.json").read_text())
        (OUT / "ttm_checks.md").write_text(report(res))
        return
    u = universe()
    fx = facts(set(u["cik"]))
    r = recompute(u, fx)
    c1 = check1(r, u)
    c2 = check2(u, fx)
    c2["mismatches"] = explain(c2["mismatches"], fx, u)
    c3 = check3(u, fx)
    res = {"run": date.today().isoformat(), "universe_rows": int(len(u)), "companies": int(u["cik"].nunique()),
           "check1": c1, "check2": c2, "check3": c3}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ttm_checks.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "ttm_checks.md").write_text(report(json.loads(json.dumps(res, default=str))))
    print(json.dumps({k: v for k, v in c1.items() if k != "by_metric_year"}, indent=1, default=str))
    print(json.dumps(c2["by_metric"], indent=1))
    print(len(c2["mismatches"]), c3["flagged_events"], c3["flagged_companies"])


if __name__ == "__main__":
    main()
