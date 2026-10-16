"""B5 input audit (owner, 2026-10-16 13:03Z, items 1 and 2): which observations the S2a revenue fallback, the H1
common-period rule and the foreign-form rule affect, traced at input level on 2015-2022 data.

No price, return, score, ranking or NAV is computed or read: only SEC fact rows (filed <= 2022-12-31) through
`edge_b5_inputs`, for the large-band company-months that pass the Phase A quality rule (`edge_ttm_checks.universe`).

Usage: python3 edge_b5_input_audit.py  ->  equity/reports/research/edge/b5_input_audit.{md,json}
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

import edge_b5
import edge_b5_inputs as bi
import edge_ttm_checks as tc
import stage2
import xsection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "equity"))
from equity import panel  # noqa: E402

OUT = tc.OUT
METRICS = ["revenue", "ocf", "capex", "gross_profit", "cost_of_revenue", "total_assets"]
NAMED = {40704: "General Mills", 1551182: "Eaton", 80424: "Procter & Gamble", 1635327: "Flutter (CIK of The Stars Group)"}


def facts(ciks: set[int]) -> dict[int, dict[str, list[dict]]]:
    out: dict[int, dict[str, list[dict]]] = {}
    for r in panel.read(xsection.DATA / "sec_facts_panel.csv.gz", ciks):
        if r["metric"] in METRICS and r["unit"] == "USD" and r["filed"] <= tc.CUT:
            out.setdefault(r["cik"], {}).setdefault(r["metric"], []).append(r)
    return out


def inputs() -> pd.DataFrame:
    u = tc.universe()
    fx = facts(set(u["cik"]))
    recs = []
    for cik, month in zip(u["cik"], u["month"].dt.strftime("%Y-%m-%d")):
        c = bi.company_month(fx.get(cik, {}), month, align=True)  # align=True only to count the diagnostic
        recs.append({"cik": cik, "month": month, **c})
    d = pd.DataFrame(recs)
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", usecols=["cik", "name", "sic"])
    d = d.merge(comp, on="cik", how="left")
    d["financial"] = d["sic"].map(stage2.sic_group) == "finance"
    return d


def paths(d: pd.DataFrame) -> pd.DataFrame:
    m = pd.to_datetime(d["month"])
    age = lambda c: (m - pd.to_datetime(d[c])).dt.days  # noqa: E731
    d = d.copy()
    d["gp_fresh"] = d["gross_profit"].notna() & age("gp_end").between(0, edge_b5.FRESH_DAYS)
    d["gp_stale"] = d["gross_profit"].notna() & ~d["gp_fresh"]
    d["alt_fresh"] = (d["revenue"].notna() & d["cost_of_revenue"].notna() & (d["rev_end"] == d["cor_end"])
                      & age("rev_end").between(0, edge_b5.FRESH_DAYS))
    d["s2a_path"] = "none"
    d.loc[d["alt_fresh"], "s2a_path"] = "fallback"
    d.loc[d["gp_fresh"], "s2a_path"] = "gross_profit_tag"
    d["fallback_conflict"] = (d["s2a_path"] == "fallback") & d["rev_conflict"].astype(bool)
    both = d["ocf_end"].notna() & d["capex_end"].notna()
    d["h1_mismatch"] = both & (d["ocf_end"] != d["capex_end"])
    d["h1_align_fresh"] = d["h1_mismatch"] & d["aligned"] & age("fcf_end").between(0, edge_b5.FRESH_DAYS)
    return d


def summarise(d: pd.DataFrame) -> dict:
    nf = d[~d["financial"]]
    both = d["ocf_end"].notna() & d["capex_end"].notna()
    fb = nf["s2a_path"] == "fallback"
    ratio = nf.loc[fb, "rev_ratio"].astype(float)
    bins = [0, 1.0000001, 1.05, 1.10, 1.25, 1.5, 2.0, float("inf")]
    dist = pd.cut(ratio, bins, right=True).value_counts().sort_index()
    conf = nf[nf["fallback_conflict"]].groupby(["cik", "name"]).agg(
        rows=("month", "size"), first=("month", "min"), last=("month", "max"),
        worst_ratio=("rev_ratio", "max")).reset_index().sort_values("rows", ascending=False)
    named = {}
    for cik, label in NAMED.items():
        x = d[d["cik"] == cik]
        named[label] = {"cik": cik, "eligible_rows": int(len(x)),
                        "first": x["month"].min() if len(x) else None, "last": x["month"].max() if len(x) else None,
                        "s2a_paths": x["s2a_path"].value_counts().to_dict(),
                        "fallback_conflict_rows": int(x["fallback_conflict"].sum()),
                        "conflict_months": f"{x.loc[x['fallback_conflict'], 'month'].min()} to "
                                           f"{x.loc[x['fallback_conflict'], 'month'].max()}" if x["fallback_conflict"].any() else None,
                        "foreign_form_rows": int((x["foreign_form"] == True).sum())}  # noqa: E712
    ff = d[d["foreign_form"] == True].groupby(["cik", "name"]).agg(  # noqa: E712
        rows=("month", "size"), first=("month", "min"), last=("month", "max"),
        financial=("financial", "first")).reset_index()
    return {
        "run": date.today().isoformat(), "rows": int(len(d)), "nonfinancial_rows": int(len(nf)),
        "companies": int(d["cik"].nunique()),
        "h1": {"both_present": int(both.sum()), "mismatched_ends": int(d["h1_mismatch"].sum()),
               "mismatched_nonfinancial": int((d["h1_mismatch"] & ~d["financial"]).sum()),
               "alignment_would_recover_fresh": int(d["h1_align_fresh"].sum())},
        "s2a": {"paths_nonfinancial": nf["s2a_path"].value_counts().to_dict(),
                "gp_stale_nonfinancial": int(nf["gp_stale"].sum()),
                "gp_stale_then_fallback": int((nf["gp_stale"] & (nf["s2a_path"] == "fallback")).sum()),
                "gp_stale_then_none": int((nf["gp_stale"] & (nf["s2a_path"] == "none")).sum()),
                "fallback_conflict_rows": int(nf["fallback_conflict"].sum()),
                "fallback_conflict_companies": int(conf["cik"].nunique()),
                "ratio_distribution": {str(k): int(v) for k, v in dist.items()},
                "conflicts": conf.to_dict("records")},
        "foreign_form": {"rows": int((d["foreign_form"] == True).sum()), "companies": ff.to_dict("records")},  # noqa: E712
        "named": named,
    }


def report(s: dict) -> str:
    h, a = s["h1"], s["s2a"]
    p = a["paths_nonfinancial"]
    L = ["# B5 input audit: revenue fallback, common period ends, foreign forms", "",
         f"Run {s['run']}. Large-band company-months 2015-01 to 2022-12 passing the Phase A quality rule: "
         f"{s['rows']:,} rows ({s['nonfinancial_rows']:,} non-financial), {s['companies']} companies. SEC facts "
         "filed after 2022-12-31 are never read. **No price, return, score, ranking or NAV is computed.**", "",
         "> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the "
         "2026 price download are missing entirely. Nothing here bounds that bias.", "",
         "## 1. H1: operating cash flow and capex period ends", "",
         f"- Both inputs present: {h['both_present']:,} rows. Latest TTM period ends differ: "
         f"**{h['mismatched_ends']:,}** ({h['mismatched_ends'] / h['both_present']:.1%}; "
         f"{h['mismatched_nonfinancial']:,} non-financial).",
         "- Registered rule (v2 §2.1, unchanged by ADDENDUM_1 §2): those rows have no FCF, so no H1 score. "
         "No alignment is attempted.",
         f"- Diagnostic only: aligning both inputs to the earlier common end would recover "
         f"{h['alignment_would_recover_fresh']:,} rows that are also fresh (≤ 183 days). Not adopted.",
         "- The earlier figure (650 of 39,273, v2 §1.1) was measured on the dataset's carried-forward values; this "
         "count recomputes each input as known at each month-end, which is what the trial will use.", "",
         "## 2. S2a: which gross profit each non-financial row would use", "",
         "| Path | Rows |", "|---|---:|",
         f"| `GrossProfit` tag, own end ≤ 183 days | {p.get('gross_profit_tag', 0):,} |",
         f"| Fallback: revenue − cost of revenue, common end ≤ 183 days | {p.get('fallback', 0):,} |",
         f"| Neither (no S2a score) | {p.get('none', 0):,} |", "",
         f"- Stale `GrossProfit` (> 183 days) is never used: {a['gp_stale_nonfinancial']:,} rows; of these "
         f"{a['gp_stale_then_fallback']:,} fall back to a fresh revenue − cost of revenue and "
         f"{a['gp_stale_then_none']:,} have no score.", "",
         "### Revenue-concept conflicts among fallback rows (ADDENDUM_1 §1)", "",
         "Ratio = largest value any listed revenue concept reports for the same period ÷ the selected concept's "
         "value (worst period of the TTM). Above 1.10, or a selected value ≤ 0, is a conflict and the fallback is "
         "unavailable.", "", "| Ratio | Fallback rows |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in a["ratio_distribution"].items()]
    L += ["", f"**{a['fallback_conflict_rows']:,} fallback rows in {a['fallback_conflict_companies']} companies "
          "conflict** and become unavailable:", "", "| CIK | Company | Rows | First | Last | Worst ratio |",
          "|---|---|---:|---|---|---:|"]
    L += [f"| {r['cik']} | {r['name']} | {r['rows']} | {r['first']} | {r['last']} | {r['worst_ratio']:.2f} |"
          for r in a["conflicts"]]
    L += ["", "## 3. Foreign annual forms (ADDENDUM_1 §3)", "",
          f"{s['foreign_form']['rows']:,} rows whose latest balance sheet came from a 20-F or 40-F become unavailable "
          "to both trials:", "", "| CIK | Company | Rows | First | Last | Financial |", "|---|---|---:|---|---|---|"]
    L += [f"| {r['cik']} | {r['name']} | {r['rows']} | {r['first']} | {r['last']} | {r['financial']} |"
          for r in s["foreign_form"]["companies"]]
    L += ["", "## 4. The named cases", "", "| Company | Eligible rows | S2a paths | Fallback conflicts | Foreign-form rows |",
          "|---|---:|---|---|---:|"]
    for k, v in s["named"].items():
        paths_ = ", ".join(f"{a_} {b_}" for a_, b_ in v["s2a_paths"].items())
        conf = f"{v['fallback_conflict_rows']} ({v['conflict_months']})" if v["fallback_conflict_rows"] else "0"
        L.append(f"| {k} | {v['eligible_rows']} ({v['first']} to {v['last']}) | {paths_} | {conf} | {v['foreign_form_rows']} |")
    L += ["", "H1 does not use revenue, so the revenue defect cannot reach H1 scores.", ""]
    return "\n".join(L)


def main() -> None:
    d = paths(inputs())
    s = summarise(d)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b5_input_audit.json").write_text(json.dumps(s, indent=1, default=str))
    (OUT / "b5_input_audit.md").write_text(report(json.loads(json.dumps(s, default=str))))
    print(json.dumps({k: s[k] for k in ("rows", "h1")}, indent=1), json.dumps(s["named"], indent=1, default=str))


if __name__ == "__main__":
    main()
