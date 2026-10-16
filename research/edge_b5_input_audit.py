"""B5 input audit (owner reviews 2026-10-16 13:03Z and 13:34Z): which observations the S2a revenue tests, the
restated-period test, the H1 common-period rule and the company-identity options affect, at input level, 2015-2022.

No return, score, ranking or NAV is computed or read. Inputs: SEC fact rows (filed <= 2022-12-31) through
`edge_b5_inputs`, and, for the identity section only, the universe's market cap and total assets (market cap is a
price level, used to test whether price and share count belong to the filer; it is not a performance measure).
Universe: the large-band company-months that pass the Phase A quality rule (`edge_ttm_checks.universe`).

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
IMPLAUSIBLE = 100.0  # option C: market cap above 100 x total assets
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
    d = d.merge(u[["cik", "month", "ticker", "mcap", "total_assets"]].assign(month=u["month"].dt.strftime("%Y-%m-%d"))
                .rename(columns={"total_assets": "ta_dataset"}), on=["cik", "month"], how="left")
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
    d["fallback_blocked"] = (d["s2a_path"] == "fallback") & (d["rev_conflict"].astype(bool) | d["cor_restated"].astype(bool))
    d["reasons"] = [("+".join(r) if r else "") + ("+COR-T2" if c else "") for r, c in zip(d["rev_reasons"], d["cor_restated"])]
    d["reasons"] = d["reasons"].str.lstrip("+")
    both = d["ocf_end"].notna() & d["capex_end"].notna()
    d["h1_mismatch"] = both & (d["ocf_end"] != d["capex_end"])
    d["h1_align_fresh"] = d["h1_mismatch"] & d["aligned"] & age("fcf_end").between(0, edge_b5.FRESH_DAYS)
    d["h1_fcf"] = both & ~d["h1_mismatch"] & age("ocf_end").between(0, edge_b5.FRESH_DAYS)
    d["mcap_to_assets"] = d["mcap"] / d["ta_dataset"].where(d["ta_dataset"] > 0)
    return d


# Identity review of the 13 companies with a foreign-form balance sheet (input evidence in the report's table;
# judgement by Claude on 2026-10-16, not verified against filings or an independent price source).
IDENTITY_REVIEW = {
    1635327: "INVALID identity: CIK filed as The Stars Group (40-F) in 2018-20, priced with Flutter's FLUT",
    1527762: "INVALID units: market cap 1,579x assets, ADS price times ordinary shares (financial, never scored)",
    1541157: "INVALID units: market cap 334x assets, ADS price times ordinary shares",
    1611747: "INVALID units: $16bn market cap for a small biotech with no total assets in the data",
    1873875: "INVALID units: market cap 540x assets, ADS price times ordinary shares",
    818686: "plausible: NYSE ADS 1:1, market cap 0.9x assets",
    849395: "plausible: NYSE listing, market cap 0.8x assets",
    1159152: "plausible: market cap 3.7x assets (ADS ratio changed over time; not verified)",
    1413447: "plausible: Nasdaq common shares, market cap 1.5x assets",
    1567094: "plausible: NYSE common shares, market cap 0.3x assets",
    1594805: "plausible: NYSE class A shares (diluted count), market cap 20x assets",
    1650372: "plausible: Nasdaq class A shares (diluted count), market cap 14x assets",
    1704292: "plausible: Nasdaq ADS, market cap 30x assets (ADS ratio not verified)",
}


def summarise(d: pd.DataFrame) -> dict:
    nf = d[~d["financial"]]
    fb = nf["s2a_path"] == "fallback"
    blocked = nf[nf["fallback_blocked"]]
    by_reason = blocked["reasons"].value_counts().to_dict()
    comp = blocked.groupby(["cik", "name", "reasons"]).agg(rows=("month", "size"), first=("month", "min"),
                                                           last=("month", "max")).reset_index()
    named = {}
    for cik, label in NAMED.items():
        x = d[d["cik"] == cik]
        named[label] = {"cik": cik, "eligible_rows": int(len(x)), "first": x["month"].min(), "last": x["month"].max(),
                        "s2a_paths": x["s2a_path"].value_counts().to_dict(),
                        "blocked": x.loc[x["fallback_blocked"], "reasons"].value_counts().to_dict(),
                        "foreign_form_rows": int((x["foreign_form"] == True).sum())}  # noqa: E712
    ff = d[d["foreign_form"] == True]  # noqa: E712
    ffc = ff.groupby(["cik", "name"]).agg(rows=("month", "size"), first=("month", "min"), last=("month", "max"),
                                          ticker=("ticker", "first"), financial=("financial", "first"),
                                          mcap_bn=("mcap", lambda v: round(v.median() / 1e9, 1)),
                                          ta_bn=("ta_dataset", lambda v: round(v.median() / 1e9, 2)),
                                          ratio=("mcap_to_assets", "median")).reset_index()
    ffc["review"] = ffc["cik"].map(IDENTITY_REVIEW)
    imp = d[d["mcap_to_assets"] > IMPLAUSIBLE].groupby(["cik", "name"]).agg(
        rows=("month", "size"), first=("month", "min"), last=("month", "max"), financial=("financial", "first"),
        ratio_min=("mcap_to_assets", "min")).reset_index()
    genuine_max = d.loc[d["cik"].isin([1585521, 1650372, 1594805, 1704292]), "mcap_to_assets"].max()
    mid = d[(d["mcap_to_assets"] > 25) & (d["mcap_to_assets"] <= IMPLAUSIBLE)].groupby(["cik", "name"]).agg(
        rows=("month", "size"), ratio_max=("mcap_to_assets", "max")).reset_index().sort_values("ratio_max")
    invalid = [c for c, v in IDENTITY_REVIEW.items() if v.startswith("INVALID")]
    opts = {}
    for k, excl in (("A_broad_foreign_form", d["foreign_form"] == True),  # noqa: E712
                    ("B_cik_1635327_only", d["cik"] == 1635327),
                    ("C_cik_1635327_plus_mcap_over_100x_assets", (d["cik"] == 1635327) | (d["mcap_to_assets"] > IMPLAUSIBLE))):
        x = d[excl]
        opts[k] = {"rows": int(len(x)), "companies": int(x["cik"].nunique()),
                   "invalid_found_removed": sorted(set(invalid) & set(x["cik"])),
                   "plausible_removed": sorted(set(ffc.loc[~ffc["cik"].isin(invalid), "cik"]) & set(x["cik"])),
                   "other_companies_removed": sorted(set(x["cik"]) - set(ffc["cik"]))}
    h = d["h1_fcf"]
    return {
        "run": date.today().isoformat(), "rows": int(len(d)), "nonfinancial_rows": int(len(nf)),
        "companies": int(d["cik"].nunique()),
        "h1": {"both_present": int((d["ocf_end"].notna() & d["capex_end"].notna()).sum()),
               "mismatched_ends": int(d["h1_mismatch"].sum()),
               "mismatched_nonfinancial": int((d["h1_mismatch"] & ~d["financial"]).sum()),
               "alignment_would_recover_fresh": int(d["h1_align_fresh"].sum()),
               "fresh_common_end_rows": int(h.sum()),
               "t2_ocf_or_capex_rows": int((h & (d["ocf_restated"] | d["capex_restated"])).sum()),
               "t2_nonfinancial_rows": int((h & ~d["financial"] & (d["ocf_restated"] | d["capex_restated"])).sum()),
               "t2_companies": int(d.loc[h & (d["ocf_restated"] | d["capex_restated"]), "cik"].nunique())},
        "s2a": {"paths_nonfinancial": nf["s2a_path"].value_counts().to_dict(),
                "gp_stale_nonfinancial": int(nf["gp_stale"].sum()),
                "gp_stale_then_fallback": int((nf["gp_stale"] & (nf["s2a_path"] == "fallback")).sum()),
                "gp_stale_then_none": int((nf["gp_stale"] & (nf["s2a_path"] == "none")).sum()),
                "fallback_rows": int(fb.sum()), "fallback_blocked_rows": int(len(blocked)),
                "fallback_blocked_companies": int(blocked["cik"].nunique()), "by_reason": by_reason,
                "blocked_by_company": comp.sort_values(["reasons", "rows"], ascending=[True, False]).to_dict("records"),
                "gp_tag_t2_rows": int(((nf["s2a_path"] == "gross_profit_tag") & nf["gp_restated"]).sum()),
                "gp_tag_t2_companies": int(nf.loc[(nf["s2a_path"] == "gross_profit_tag") & nf["gp_restated"], "cik"].nunique())},
        "identity": {"foreign_form_rows": int(len(ff)), "foreign_form_companies": ffc.to_dict("records"),
                     "implausible_over_100x": imp.to_dict("records"), "genuine_max_ratio_seen": float(genuine_max),
                     "between_25x_and_100x": mid.to_dict("records"), "options": opts},
        "named": named,
    }


def report(s: dict) -> str:
    h, a, idn = s["h1"], s["s2a"], s["identity"]
    p = a["paths_nonfinancial"]
    L = ["# B5 input audit: revenue tests, restated periods, common period ends, company identity", "",
         f"Run {s['run']}. Large-band company-months 2015-01 to 2022-12 passing the Phase A quality rule: "
         f"{s['rows']:,} rows ({s['nonfinancial_rows']:,} non-financial), {s['companies']} companies. SEC facts "
         "filed after 2022-12-31 are never read. **No return, score, ranking or NAV is computed.**", "",
         "> **Survivorship (material, unbounded):** the universe needs a price, so companies that delisted before the "
         "2026 price download are missing entirely. Nothing here bounds that bias.", "",
         "## 1. H1: operating cash flow and capex", "",
         f"- Latest TTM ends differ in **{h['mismatched_ends']:,}** of {h['both_present']:,} rows "
         f"({h['mismatched_nonfinancial']:,} non-financial): no H1 score (owner decision, no alignment). An alignment "
         f"step would have recovered {h['alignment_would_recover_fresh']:,} fresh rows; not adopted.",
         f"- Rows with a fresh common end: {h['fresh_common_end_rows']:,}. Of these, **{h['t2_ocf_or_capex_rows']:,}** "
         f"({h['t2_nonfinancial_rows']:,} non-financial, {h['t2_companies']} companies) have an OCF or capex TTM that "
         "mixes bases (test T2). **Open decision: T2 is not applied to H1 yet.**", "",
         "## 2. S2a: which gross profit each non-financial row would use", "",
         "| Path | Rows |", "|---|---:|",
         f"| `GrossProfit` tag, own end ≤ 183 days | {p.get('gross_profit_tag', 0):,} |",
         f"| Fallback: revenue − cost of revenue, common end ≤ 183 days | {p.get('fallback', 0):,} |",
         f"| Neither (no S2a score) | {p.get('none', 0):,} |", "",
         f"- A `GrossProfit` value older than 183 days is never used: {a['gp_stale_nonfinancial']:,} rows; "
         f"{a['gp_stale_then_fallback']:,} fall back to a fresh revenue − cost of revenue, "
         f"{a['gp_stale_then_none']:,} have no score.",
         f"- `GrossProfit`-tag rows whose TTM mixes bases (T2): {a['gp_tag_t2_rows']:,} in "
         f"{a['gp_tag_t2_companies']} companies. **Open decision: T2 is not applied to the tag path yet.**", "",
         "### Fallback rows blocked by the revenue tests (ADDENDUM_2 §1)", "",
         f"**{a['fallback_blocked_rows']:,} of {a['fallback_rows']:,} fallback rows, "
         f"{a['fallback_blocked_companies']} companies.** By test (T0 revenue ≤ 0; T1 same-filing concept conflict; "
         "T2 revenue TTM mixes bases; COR-T2 cost of revenue TTM mixes bases):", "",
         "| Tests failed | Rows |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in sorted(a["by_reason"].items())]
    L += ["", "| CIK | Company | Tests | Rows | First | Last |", "|---|---|---|---:|---|---|"]
    L += [f"| {r['cik']} | {r['name']} | {r['reasons']} | {r['rows']} | {r['first']} | {r['last']} |"
          for r in a["blocked_by_company"]]
    L += ["", "## 3. Company identity and price units", "",
          f"### 3.1 The {len(idn['foreign_form_companies'])} companies with a 20-F/40-F balance sheet "
          f"({idn['foreign_form_rows']} rows)", "",
          "| CIK | Company | Ticker | Rows | First | Last | Median market cap $bn | Median assets $bn | Cap ÷ assets | Review |",
          "|---|---|---|---:|---|---|---:|---:|---:|---|"]
    for r in idn["foreign_form_companies"]:
        ratio = "n/a" if r["ratio"] != r["ratio"] else f"{r['ratio']:,.1f}"
        L.append(f"| {r['cik']} | {r['name']} | {r['ticker']} | {r['rows']} | {r['first']} | {r['last']} | "
                 f"{r['mcap_bn']} | {r['ta_bn']} | {ratio} | {r['review']} |")
    L += ["", f"### 3.2 Market cap above 100 × total assets (all companies; highest genuine case seen "
          f"{idn['genuine_max_ratio_seen']:.0f}×, Zoom in late 2020)", "",
          "| CIK | Company | Rows | First | Last | Financial | Lowest ratio |", "|---|---|---:|---|---|---|---:|"]
    L += [f"| {r['cik']} | {r['name']} | {r['rows']} | {r['first']} | {r['last']} | {r['financial']} | {r['ratio_min']:,.0f} |"
          for r in idn["implausible_over_100x"]]
    L += ["", "### 3.3 Between 25× and 100× (kept by every option; errors and genuine cases overlap here)", "",
          "| CIK | Company | Rows | Highest ratio |", "|---|---|---:|---:|"]
    L += [f"| {r['cik']} | {r['name']} | {r['rows']} | {r['ratio_max']:.0f} |" for r in idn["between_25x_and_100x"]]
    L += ["", "### 3.4 Options compared (input evidence only)", "",
          "| Option | Rows removed | Companies | Invalid companies removed | Plausible foreign filers removed | Other companies removed |",
          "|---|---:|---:|---|---|---|"]
    for k, v in idn["options"].items():
        L.append(f"| {k} | {v['rows']} | {v['companies']} | {v['invalid_found_removed']} | {v['plausible_removed']} | "
                 f"{len(v['other_companies_removed'])} |")
    L += ["", "## 4. The named cases", "", "| Company | Eligible rows | S2a paths | Fallback rows blocked | Foreign-form rows |",
          "|---|---:|---|---|---:|"]
    for k, v in s["named"].items():
        paths_ = ", ".join(f"{a_} {b_}" for a_, b_ in v["s2a_paths"].items())
        L.append(f"| {k} | {v['eligible_rows']} ({v['first']} to {v['last']}) | {paths_} | {v['blocked'] or 0} | "
                 f"{v['foreign_form_rows']} |")
    L += ["", "H1 does not use revenue, so the revenue tests cannot change H1 scores.", ""]
    return "\n".join(L)


def main() -> None:
    d = paths(inputs())
    s = summarise(d)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b5_input_audit.json").write_text(json.dumps(s, indent=1, default=str))
    (OUT / "b5_input_audit.md").write_text(report(json.loads(json.dumps(s, default=str))))
    print(json.dumps({k: s[k] for k in ("rows", "h1")}, indent=1), json.dumps(s["identity"]["options"], indent=1))


if __name__ == "__main__":
    main()
