"""Check 4 sampling-frame coverage: why eligible company-months have no score (owner request, 20 Oct 2026).

The Check 4 frame (reconstruct_holdings.py) holds only scored company-months. This script classifies the others:
rows that pass every eligibility rule the engine applies before scoring (large band, point-in-time quality rule,
close >= $1, non-financial, decision month 2015-01..2022-11) but whose primary score is NaN.

Read only. It rebuilds the same panel with the same frozen functions as reconstruct_holdings.py (frozen checkout
verified first), recomputes the frozen intermediates (`edge_b5.h1_velocity`, `s2a_profitability`, `identity_ok`)
and assigns each unscored row the FIRST failing step in the frozen formula's own order. It never fills, imputes or
re-scores anything and changes no selection rule. Output: one JSON summary.

    B5 frozen checkout:  python3 research/check4/missing_scores.py --frozen <a4a07d7 checkout> --out docs/edge/check4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct_holdings as rh  # noqa: E402

# Each reason: (label, kind, meaning). "rule": a frozen rule excludes the row by design (expected). "data": an input
# is absent from the SEC facts as captured; the company may not report that line at all (expected for some business
# models) or the capture may have missed it (a possible data or tag-mapping problem). Only a source check can tell
# them apart. "inherits": the row fails because a row 12 or 24 months earlier failed; `inherited_from` says why.
H1_STEPS = [
    ("no_ocf_or_capex", "data", "operating cash flow or capital expenditure not found in the SEC facts"),
    ("ocf_capex_period_ends_differ", "rule", "OCF and capex TTM periods end on different dates (fcf_end is None)"),
    ("fcf_stale", "rule", "the TTM FCF period ended more than 183 days before the month-end"),
    ("identity_rule", "rule", "ADDENDUM_2 rule C: CIK 1635327, or mcap > 100x total assets"),
    ("restated_flag", "rule", "OCF or capex TTM mixes bases (T2 restated flag true or missing: fail closed)"),
    ("no_total_assets", "data", "total assets missing or not positive"),
    ("no_shares", "data", "no share count (cover-page or diluted)"),
    ("no_row_12m_earlier", "rule", "the company has no row 12 months earlier (not in the monthly data then)"),
    ("fcf_12m_earlier_unavailable", "inherits", "FCF 12 months earlier unavailable (any of the reasons above, then)"),
    ("share_or_split_undefined", "data", "shares or split factor at t-12 undefined (missing prices or shares)"),
    ("share_guard", "rule", "|ln q| > ln 3: share count changed more than 3x (merger, spin-off or share error)"),
    ("fcf_periods_not_a_year_apart", "rule", "TTM periods at t and t-12 not 350-380 days apart"),
    ("no_row_24m_earlier_or_G_12m_earlier", "inherits", "G 12 months earlier unavailable (history or inputs then)"),
    ("fcf_chain_not_a_year_apart", "rule", "TTM periods at t-12 and t-24 not 350-380 days apart"),
    ("unexplained", "data", "none of the frozen steps fails; should be zero"),
]
S2A_STEPS = [
    ("identity_rule", "rule", "ADDENDUM_2 rule C: CIK 1635327, or mcap > 100x total assets"),
    ("no_total_assets", "data", "total assets missing or not positive"),
    ("no_gp_and_no_revenue_cost", "data", "neither gross profit nor both revenue and cost of revenue found"),
    ("gp_and_revenue_cost_stale", "rule", "every available gross-profit route ended more than 183 days before"),
    ("gp_restated_and_no_fallback", "rule", "GrossProfit TTM mixes bases (T2) and revenue - cost is unavailable"),
    ("revenue_cost_period_ends_differ", "rule", "no fresh GP; revenue and cost of revenue periods end differently"),
    ("revenue_conflict_or_cost_restated", "rule", "no fresh GP; revenue fails T0-T2 or cost of revenue mixes bases"),
    ("no_sic_group", "data", "profitability exists but no SIC group, so no within-group rank"),
    ("unexplained", "data", "none of the frozen steps fails; should be zero"),
]


def first_reason(conds: list, steps: list, index):
    """conds[i] is a boolean Series: step i fails. Returns the first failing step's label per row."""
    import pandas as pd
    out = pd.Series(steps[-1][0], index=index, dtype=object)
    done = pd.Series(False, index=index)
    for (label, _, _), c in zip(steps, conds):
        hit = c.reindex(index).fillna(False).astype(bool) & ~done
        out[hit] = label
        done |= hit
    return out


def h1_reasons(b5, df):
    import numpy as np
    import pandas as pd
    d = b5.h1_velocity(df.assign(_i=np.arange(len(df))))
    d["G_12"] = b5._lag(d, "G", 12)
    d["fcf_end_24"] = b5._lag(d, "fcf_end", 24)
    d["row_12"] = b5._lag(d.assign(one=1.0), "one", 12).notna()
    m = d["month"]
    fresh = b5._days(d["fcf_end"], m).between(0, b5.FRESH_DAYS)
    conds = [
        d["ocf"].isna() | d["capex"].isna(),
        d["fcf_end"].isna(),
        ~fresh,
        ~b5.identity_ok(d),
        ~(b5._clean(d, "ocf_restated") & b5._clean(d, "capex_restated")),
        ~(d["total_assets"] > 0),
        ~(d["sh"] > 0),
        ~d["row_12"],
        d["fcf_12"].isna(),
        ~(d["sh_12"] > 0) | d["q"].isna(),
        ~(np.log(d["q"]).abs() <= b5.SHARE_GUARD),
        ~b5._days(d["fcf_end_12"], d["fcf_end"]).between(*b5.YEAR_DAYS),
        d["G_12"].isna(),
        ~b5._days(d["fcf_end_24"], d["fcf_end_12"]).between(*b5.YEAR_DAYS),
        pd.Series(True, index=d.index),
    ]
    r = first_reason(conds, H1_STEPS, d.index)
    # what failed at the earlier row, for the two inherited reasons (its own G-level reason, or "G ok")
    g_steps = [x[0] for x in H1_STEPS[:12]]
    g_reason = first_reason(conds[:12] + [pd.Series(True, index=d.index)], H1_STEPS[:12] + [("G_ok", "", "")],
                            d.index).where(d["G"].isna(), "G_ok")
    codes = {lab: i for i, lab in enumerate(g_steps + ["G_ok"])}
    lag12 = b5._lag(d.assign(code=g_reason.map(codes).astype(float)), "code", 12)
    lab = {i: l for l, i in codes.items()}
    inh = lag12.map(lambda v: lab.get(int(v)) if v == v else "no_row_then")
    inherited = inh.where(r.isin(["fcf_12m_earlier_unavailable", "no_row_24m_earlier_or_G_12m_earlier"]))
    back = lambda x: pd.Series(x.to_numpy(), index=d["_i"].to_numpy()).sort_index().set_axis(df.index)
    return back(r), back(inherited)


def s2a_reasons(b5, df):
    import pandas as pd
    m = pd.to_datetime(df["month"])
    fresh_gp = df["gross_profit"].notna() & b5._days(df["gp_end"], m).between(0, b5.FRESH_DAYS)
    has_rc = df["revenue"].notna() & df["cost_of_revenue"].notna()
    fresh_rc = has_rc & b5._days(df["rev_end"], m).between(0, b5.FRESH_DAYS)
    ends_match = df["rev_end"] == df["cor_end"]
    clean_rc = b5._clean(df, "rev_conflict") & b5._clean(df, "cor_restated")
    gp_clean = b5._clean(df, "gp_restated")
    alt_ok = has_rc & ends_match & fresh_rc & clean_rc
    gpa = b5.s2a_profitability(df)
    conds = [
        ~b5.identity_ok(df),
        ~(df["total_assets"] > 0),
        df["gross_profit"].isna() & ~has_rc,
        ~fresh_gp & ~fresh_rc,
        fresh_gp & ~gp_clean & ~alt_ok,
        ~ends_match & ~(fresh_gp & gp_clean),
        ~clean_rc & ~(fresh_gp & gp_clean),
        gpa.notna() & df["group"].isna(),
        pd.Series(True, index=df.index),
    ]
    return first_reason(conds, S2A_STEPS, df.index), None


def summarise(reason, inherited, base_unscored, df, steps, names):
    import pandas as pd
    r = reason[base_unscored]
    years = pd.to_datetime(df.loc[base_unscored, "month"]).dt.year
    kind = {s[0]: s[1] for s in steps}
    out = {"total": int(base_unscored.sum()), "by_reason": {}, "by_kind": {}, "by_year": {}}
    for label, k, desc in steps:
        sel = r == label
        if not sel.any():
            continue
        out["by_reason"][label] = {"rows": int(sel.sum()), "companies": int(df.loc[sel[sel].index, "cik"].nunique()),
                                   "kind": k, "meaning": desc}
    for k in ("rule", "data", "inherits"):
        out["by_kind"][k] = int(r.map(kind).eq(k).sum())
    if inherited is not None:
        i = inherited[base_unscored].dropna()
        for label in i.index.map(r).unique():
            sel = r.loc[i.index] == label
            out["by_reason"][label]["inherited_from"] = i[sel].value_counts().to_dict()
    for label in out["by_reason"]:
        sel = r == label
        top = df.loc[sel[sel].index].groupby("cik").size().sort_values(ascending=False, kind="stable").head(8)
        out["by_reason"][label]["top_companies"] = [{"cik": int(c), "name": names.get(int(c), ""), "rows": int(n)}
                                                    for c, n in top.items()]
        out["by_reason"][label]["by_group"] = df.loc[sel[sel].index, "group"].fillna("(none)").value_counts().to_dict()
    for y, g in r.groupby(years):
        out["by_year"][int(y)] = g.value_counts().to_dict()
    return out


def analyse(frozen: Path) -> dict:
    import pandas as pd
    provenance = rh.verify_frozen(frozen)
    mods = rh.import_frozen(frozen)
    b5, run = mods[0], mods[1]
    df, _ = rh.load_panel(mods)
    panels = run.score_panels(df)
    pm = pd.to_datetime(df["month"])
    import xsection
    names = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "name"]).set_index("cik")["name"].to_dict()
    result = {"label": "Check 4 frame coverage: reasons for missing scores (no imputation, no rule change)",
              "provenance": provenance, "trials": {}}
    for key, reasons, steps in (("H1", h1_reasons, H1_STEPS), ("S2A", s2a_reasons, S2A_STEPS)):
        panel = panels[key]["primary"]
        base = (panel["quality_ok"].astype(bool) & (panel["band"] == "large") & (panel["close_raw"] >= 1.0)
                & pm.between(pd.Timestamp(rh.FRAME_FIRST), pd.Timestamp(rh.FRAME_LAST))
                & ~df["financial"].astype(bool))
        unscored = base & panel["score"].isna()
        scored = base & panel["score"].notna()
        reason, inherited = reasons(b5, df)
        s = summarise(reason, inherited, unscored, df, steps, names)
        s["scored"] = int(scored.sum())
        s["unscored_share"] = round(s["total"] / (s["total"] + s["scored"]), 4)
        n_months = pm[base].nunique()
        s["per_month_unscored_mean"] = round(s["total"] / n_months, 1)
        companies_never_scored = set(df.loc[unscored, "cik"]) - set(df.loc[scored, "cik"])
        s["companies_unscored_at_least_once"] = int(df.loc[unscored, "cik"].nunique())
        s["companies_never_scored_in_window"] = len(companies_never_scored)
        s["by_group"] = df.loc[unscored, "group"].fillna("(none)").value_counts().to_dict()
        result["trials"][run.TRIALS[key]] = s
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frozen", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    res = analyse(a.frozen)
    a.out.mkdir(parents=True, exist_ok=True)
    p = a.out / "missing_scores_summary.json"
    p.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({t: {"total": v["total"], "by_kind": v["by_kind"]} for t, v in res["trials"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
