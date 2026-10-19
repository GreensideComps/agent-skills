"""Point-in-time regression tests through the B5 production path (owner review 2026-10-19, items 1 and 2).
Synthetic only: no research data is read and no trial is run.

Item 1: identity rule C's market cap comes from `xsection.load`, whose share counts are built by
`equity.monthly.company_months`; a share count filed after a decision month-end must not change that month's
market cap or rule C result. Item 2: `edge_b5_run.attach_fundamentals` (the loader the run uses) feeds S2a and H1;
a filing made after a decision month-end must not change that month's inputs, flags or eligibility."""
import csv
import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "equity"))
from equity import monthly  # noqa: E402

import edge_b5 as b5  # noqa: E402
import edge_b5_run as run  # noqa: E402
import xsection  # noqa: E402
from test_edge_b5_inputs import fact, year_and_ytd  # noqa: E402

T = "2016-08-31"  # the decision month-end
CIK = 1


# ---------- item 1: share counts -> xsection.load -> mcap -> identity rule C ----------

def share(metric, start, end, val, filed):
    return {"cik": CIK, "metric": metric, "rank": 0, "taxonomy": "dei" if metric == "shares_out" else "us-gaap",
            "concept": "c", "unit": "shares", "start": start, "end": end, "val": val, "filed": filed, "form": "10-Q",
            "fp": "", "accn": f"A-{filed}"}


def write_dataset(tmp: Path, facts: list[dict]) -> pd.DataFrame:
    """monthly_metrics and prices for one company, built by the production builder, read by xsection.load."""
    months = monthly.month_ends("2016-01-31", "2017-06-30")
    with gzip.open(tmp / "monthly_metrics.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=monthly.FIELDS)
        w.writeheader()
        w.writerows(monthly.company_months(CIK, facts, months))
    with gzip.open(tmp / "prices_monthly.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=monthly.PRICE_FIELDS)
        w.writeheader()
        w.writerows({"cik": CIK, "ticker": "X", "month": m, "close_raw": 10.0, "adjclose": 10.0, "currency": "USD"}
                    for m in months)
    return xsection.load(tmp).set_index("month")


SHARE_BASE = [fact("revenue", "2015-01-01", "2015-12-31", 100, "2016-02-20"),
              fact("total_assets", "", "2016-06-30", 1e9, "2016-08-05", form="10-Q"),
              share("shares_out", "", "2016-07-29", 2e8, "2016-08-05"),
              share("shares_diluted", "2016-01-01", "2016-06-30", 2.1e8, "2016-08-05")]
# all filed after T, all for dates on or before T: a cover count amended 1000x, a restated diluted count, and a
# late count for a date before T. Visible at T they would give mcap 2e12 = 2000 x assets (rule C exclusion).
SHARE_LATER = [share("shares_out", "", "2016-07-29", 2e11, "2016-11-10"),
               share("shares_out", "", "2016-08-30", 2e11, "2016-11-10"),
               share("shares_diluted", "2016-01-01", "2016-06-30", 2.1e11, "2016-11-10")]


def test_a_share_count_filed_after_the_decision_month_never_changes_its_mcap_or_rule_c(tmp_path):
    a, b = tmp_path / "pit", tmp_path / "with_later"
    a.mkdir(), b.mkdir()
    pit = write_dataset(a, SHARE_BASE)
    full = write_dataset(b, SHARE_BASE + SHARE_LATER)
    t = pd.Timestamp(T)
    for col in ("shares_out", "shares_diluted", "total_assets", "mcap", "band"):
        assert full.loc[t, col] == pit.loc[t, col]
    assert full.loc[t, "mcap"] == 2e9 and b5.identity_ok(full.reset_index(), "C").loc[full.index.get_loc(t)]
    # the test can fail: from the month-end after the late filing, the new count is used and rule C excludes it
    later = pd.Timestamp("2016-11-30")
    assert full.loc[later, "mcap"] == 2e12 and not b5.identity_ok(full.reset_index(), "C").loc[full.index.get_loc(later)]
    assert pit.loc[later, "mcap"] == 2e9


def test_the_cover_count_falls_back_to_diluted_only_from_facts_known_at_the_month_end(tmp_path):
    no_cover = [r for r in SHARE_BASE if r["metric"] != "shares_out"]
    late_cover = [share("shares_out", "", "2016-07-29", 2e11, "2016-11-10")]
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    pit, full = write_dataset(a, no_cover), write_dataset(b, no_cover + late_cover)
    t = pd.Timestamp(T)
    assert np.isnan(full.loc[t, "shares_out"]) and full.loc[t, "mcap"] == pit.loc[t, "mcap"] == 2.1e9


# ---------- item 2: attach_fundamentals -> S2a and H1 eligibility ----------

def clean_facts() -> dict:
    """Clean FY2015 + H1 2016 TTMs for every input (ttm end 2016-06-30, fresh at T)."""
    fx = {"revenue": year_and_ytd("revenue", 1000, 520, 500), "cost_of_revenue": year_and_ytd("cost_of_revenue", 600, 310, 300),
          "gross_profit": year_and_ytd("gross_profit", 400, 210, 200), "ocf": year_and_ytd("ocf", 150, 80, 70),
          "capex": year_and_ytd("capex", 50, 26, 25)}
    return fx


def recasts(filed: str) -> dict:
    """A later filing that recasts the prior-year half (2015 H1) of every input by half: T2 territory."""
    vals = {"revenue": 250, "cost_of_revenue": 150, "gross_profit": 100, "ocf": 35, "capex": 12}
    return {m: [fact(m, "2015-01-01", "2015-06-30", v, filed, form="10-Q", accn="RECAST")] for m, v in vals.items()}


def frame(fx: dict, months=(T,)) -> pd.DataFrame:
    df = pd.DataFrame({"cik": CIK, "month": pd.to_datetime(list(months)), "shares_out": 1e6, "shares_diluted": 1e6,
                       "total_assets": 2000.0, "close_raw": 10.0, "adjclose": 10.0, "mcap": 1e5})  # 50 x assets
    return run.attach_fundamentals(df, {CIK: fx})


def merged(a: dict, b: dict) -> dict:
    return {m: a.get(m, []) + b.get(m, []) for m in set(a) | set(b)}


def eligibility(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"s2a": b5.s2a_profitability(df).to_numpy(), "fcf": b5.h1_velocity(df)["fcf"].to_numpy()},
                        index=df["month"])


def test_a_filing_after_the_decision_month_never_changes_its_inputs_flags_or_eligibility():
    months = (T, "2016-11-30")
    base = frame(clean_facts(), months)
    late = frame(merged(clean_facts(), recasts("2016-11-05")), months)
    t0 = base.index[0]
    for c in run.FUND_COLS:
        assert (base.loc[t0, c] == late.loc[t0, c]) or (pd.isna(base.loc[t0, c]) and pd.isna(late.loc[t0, c])), c
    e_base, e_late = eligibility(base), eligibility(late)
    assert e_base.loc[pd.Timestamp(T)].notna().all()
    assert e_late.loc[pd.Timestamp(T)].equals(e_base.loc[pd.Timestamp(T)])
    # the same filing changes the month-end after it: T2 flags every input, S2a and FCF become unavailable
    after = late.iloc[1]
    assert all(bool(after[f"{k}_restated"]) for k in ("gp", "cor", "ocf", "capex"))
    assert e_late.loc[pd.Timestamp("2016-11-30")].isna().all()


def test_the_same_recast_filed_before_the_decision_month_does_change_it():
    """Sensitivity: the test above would fail if the loader used the filing date wrongly."""
    early = frame(merged(clean_facts(), recasts("2016-08-20")))
    assert all(bool(early.iloc[0][f"{k}_restated"]) for k in ("gp", "cor", "ocf", "capex"))
    assert eligibility(early).iloc[0].isna().all()


def test_the_run_never_asks_for_the_retrospective_diagnostic_or_alignment():
    src = Path(run.__file__).read_text()
    for banned in ("retro_as_of", "compare_as_of", "align=True", "_retro"):
        assert banned not in src.replace("no `retro_as_of`", "").replace("no `align`", ""), banned
    # the fact rows are cut at 2022-12-31 on read, and company_month is called with the row's own month-end only
    assert 'r["filed"] <= str(CUT.date())' in src
    assert "bi.company_month(fx_rows.get(c, {}), m)" in src
