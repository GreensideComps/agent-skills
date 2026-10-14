"""Stage 1 acceptance check (STRATEGY_V2): coverage and survivorship of the research dataset.

Reads the files `python -m equity research-data` builds and writes a markdown report:
* how many companies each month have point-in-time fundamentals, a price, a market cap, a next-month
  return, per size band, against the Stage 1 targets;
* the price-side survivorship gap: of companies that were filing and large (total assets >= $1bn),
  how many have prices, split by whether they still file today;
* a harness sanity check: the equal-weighted large-band return should track the Ken French market
  return closely. This checks the plumbing (returns, dates, bands); it tests no signal.

    RESEARCH_DATA=/path python3 stage1_coverage.py [out.md]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

import data_sources
import xsection

TARGETS = {"scored_from_2012": 2000, "large_from_2015": 300}


def main(out: Path) -> None:
    df = xsection.load()
    comp = pd.read_csv(xsection.DATA / "sec_companies.csv.gz", dtype={"cik": int})
    inv = xsection.investable(df)
    scored = inv[inv["ttm_revenue"].notna()]
    cov = xsection.coverage(df)
    cov["scored"] = scored.groupby("month").size()
    cov["scored_large"] = scored[scored["band"] == "large"].groupby("month").size()
    cov = cov.fillna(0).astype(int)

    s12 = cov.loc[cov.index >= "2012-01-31", "scored"]
    l15 = cov.loc[cov.index >= "2015-01-31", "scored_large"]
    last = cov.index.max()
    lines = ["# Stage 1 research dataset: coverage and survivorship", "",
             f"Data: SEC bulk XBRL (companyfacts, submissions) and Yahoo monthly prices; months to {last:%Y-%m}.",
             "Built by `python -m equity research-data`; files in the shared project folder `research-data/`.", "",
             "## Acceptance targets", "",
             "| Target | Required | Minimum month | Median month | Met |", "|---|---:|---:|---:|---|",
             f"| Scored US companies a month, 2012 on | {TARGETS['scored_from_2012']:,} | {s12.min():,} | {int(s12.median()):,} | "
             f"{'yes' if s12.min() > TARGETS['scored_from_2012'] else 'no'} |",
             f"| Scored large caps a month, 2015 on | {TARGETS['large_from_2015']:,} | {l15.min():,} | {int(l15.median()):,} | "
             f"{'yes' if l15.min() > TARGETS['large_from_2015'] else 'no'} |", "",
             "Scored = filing within 15 months, a USD price of at least $1, a point-in-time market cap of at least "
             "$0.3bn, a next-month return and trailing revenue.", "",
             "## Coverage each January", "",
             "| Month | Filing | With price | With market cap | Large | Mid | Small | Scored | Scored large |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mo, r in cov[cov.index.month == 1].iterrows():
        lines.append(f"| {mo:%Y-%m} | {r.filing:,} | {r.with_price:,} | {r.with_mcap:,} | {r.large:,} | {r.mid:,} | "
                     f"{r.small:,} | {r.scored:,} | {r.scored_large:,} |")

    # Price-side survivorship: large filers (by assets) with and without prices, by today's status.
    big = df[df["total_assets"] >= 1e9].merge(comp[["cik", "last_periodic", "tickers"]], on="cik", how="left")
    cutoff = (last - pd.DateOffset(months=15)).strftime("%Y-%m-%d")
    big["still_filing"] = big["last_periodic"].fillna("") >= cutoff
    lines += ["", "## Survivorship on the price side", "",
              "Companies filing with total assets of at least $1bn, and the share of them with a price that month. "
              "Companies that later stopped filing (acquired, delisted, bankrupt, deregistered) mostly have no "
              "ticker in SEC's data today, so free prices miss them.", "",
              "| Month | Still filing today: n | with price | Stopped since: n | with price |", "|---|---:|---:|---:|---:|"]
    for y in (2012, 2015, 2018, 2021, 2024):
        mo = pd.Timestamp(f"{y}-01-31")
        g = big[big["month"] == mo]
        a, b = g[g["still_filing"]], g[~g["still_filing"]]
        lines.append(f"| {mo:%Y-%m} | {len(a):,} | {a['close_raw'].notna().mean():.0%} | {len(b):,} | "
                     f"{b['close_raw'].notna().mean() if len(b) else float('nan'):.0%} |")
    stopped = comp[(comp["entity_type"] == "operating") & comp["last_periodic"].fillna("").between("2010-01-01", cutoff)]
    lines += ["", f"Operating companies that stopped periodic filing between 2010 and {cutoff}: {len(stopped):,}; "
              f"with a ticker in SEC data today: {(stopped['tickers'].fillna('') != '').sum():,}.", "",
              "Consequence: tests on this dataset include failed and acquired companies in the fundamentals but "
              "not in returns. Results are biased toward survivors, most in small caps and least in large caps; "
              "every Stage 2 result must state this, and survivorship-free prices are an owner decision.", ""]

    # Harness sanity check against the French market factor.
    ff = data_sources.french("F-F_Research_Data_Factors")
    mkt = ff["Mkt-RF"] + ff["RF"]
    ew = inv[inv["band"] == "large"].groupby("month")["ret_next"].mean()
    ew.index = ew.index + pd.offsets.MonthEnd(1)  # ret_next of month m is the return over month m+1
    j = pd.concat([ew.rename("ew_large"), mkt.rename("ff_mkt")], axis=1).dropna()
    j = j[j.index >= "2012-01-31"]
    lines += ["## Harness check", "",
              f"Equal-weighted large-band monthly return vs the Ken French US market return, {j.index.min():%Y-%m} to "
              f"{j.index.max():%Y-%m} ({len(j)} months): correlation {j['ew_large'].corr(j['ff_mkt']):.3f}, mean "
              f"{j['ew_large'].mean() * 12:.1%} vs {j['ff_mkt'].mean() * 12:.1%} a year. "
              "A correlation near 1 says returns, dates and bands line up; it tests no signal.", ""]
    out.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("stage1_coverage.md"))
