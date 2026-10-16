"""Per-input SEC loader for B5 (edge_b5_inputs), on synthetic SEC fact rows only. Written before any real use.

Owner, 2026-10-16 13:03Z, items 1, 2 and 5: per-input period ends, the H1 common-period rule, S2a staleness, the
revenue-concept rule and the foreign-form rule (ADDENDUM_1 §1-§3)."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "equity"))

from equity import panel  # noqa: E402

import edge_b5 as b5  # noqa: E402
import edge_b5_inputs as bi  # noqa: E402

CONCEPTS = {"revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
            "ocf": ["NetCashProvidedByUsedInOperatingActivities"], "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
            "gross_profit": ["GrossProfit"], "cost_of_revenue": ["CostOfRevenue"], "total_assets": ["Assets"]}


def fact(metric, start, end, val, filed, concept=None, form="10-K", accn=None):
    concept = concept or CONCEPTS[metric][0]
    return {"cik": 1, "metric": metric, "rank": CONCEPTS[metric].index(concept), "taxonomy": "us-gaap",
            "concept": concept, "unit": "USD", "start": start, "end": end, "val": float(val), "filed": filed,
            "form": form, "fp": "", "accn": accn if accn is not None else f"A-{filed}"}  # one accession per filing date


def year_and_ytd(metric, fy_val, ytd_val, prior_ytd_val, concept=None, ytd_filed="2016-08-05"):
    """FY 2015 (filed Feb 2016), H1 2016 year-to-date (filed Aug 2016) and its prior-year comparative."""
    return [fact(metric, "2015-01-01", "2015-12-31", fy_val, "2016-02-20", concept),
            fact(metric, "2016-01-01", "2016-06-30", ytd_val, ytd_filed, concept, "10-Q"),
            fact(metric, "2015-01-01", "2015-06-30", prior_ytd_val, ytd_filed, concept, "10-Q")]


# ---------- per-input period ends ----------

def test_ttm_input_reproduces_panel_ttm_and_reports_its_end_concepts_and_periods():
    rows = year_and_ytd("ocf", 100, 60, 50)
    for as_of in ("2016-03-31", "2016-08-31"):
        t, ref = bi.ttm_input(rows, as_of), panel.ttm(rows, as_of)
        assert (t["val"], t["end"], t["basis"]) == (ref["val"], ref["end"], ref["basis"])
    assert bi.ttm_input(rows, "2016-03-31")["end"] == "2015-12-31"  # the 10-Q is not public yet
    t = bi.ttm_input(rows, "2016-08-31")
    assert t["val"] == 110 and t["end"] == "2016-06-30" and t["concepts"] == ["NetCashProvidedByUsedInOperatingActivities"]
    assert t["periods"] == [("2015-01-01", "2015-12-31"), ("2016-01-01", "2016-06-30"), ("2015-01-01", "2015-06-30")]


def test_a_value_filed_after_the_month_end_is_never_used():
    rows = year_and_ytd("ocf", 100, 60, 50) + [fact("ocf", "2015-01-01", "2015-12-31", 999, "2017-02-20")]
    assert bi.ttm_input(rows, "2016-08-31")["val"] == 110  # the later restatement is invisible on 2016-08-31


# ---------- H1: common period end (item 2) ----------

def test_ocf_and_capex_with_the_same_end_give_fcf_inputs():
    f = bi.fcf_inputs(year_and_ytd("ocf", 100, 60, 50), year_and_ytd("capex", 20, 12, 10), "2016-08-31")
    assert (f["ocf"], f["capex"], f["fcf_end"]) == (110, 22, "2016-06-30")


def test_mismatched_ocf_and_capex_ends_make_fcf_unavailable_under_the_registered_rule():
    capex_no_ytd = [fact("capex", "2015-01-01", "2015-12-31", 20, "2016-02-20")]  # capex year-to-date missing
    f = bi.fcf_inputs(year_and_ytd("ocf", 100, 60, 50), capex_no_ytd, "2016-08-31")
    assert f["fcf_end"] is None and f["ocf"] is None and (f["ocf_end"], f["capex_end"]) == ("2016-06-30", "2015-12-31")
    # the diagnostic alignment (never used by a trial) would find the common FY end
    g = bi.fcf_inputs(year_and_ytd("ocf", 100, 60, 50), capex_no_ytd, "2016-08-31", align=True)
    assert (g["ocf"], g["capex"], g["fcf_end"], g["aligned"]) == (100, 20, "2015-12-31", True)


def test_missing_capex_makes_fcf_unavailable():
    assert bi.fcf_inputs(year_and_ytd("ocf", 100, 60, 50), [], "2016-08-31")["fcf_end"] is None


def test_loader_output_feeds_h1_and_a_mismatched_row_has_no_score():
    """End to end: loader -> h1_velocity. A row whose latest ocf and capex ends differ has fcf_end None, so no G."""
    df = pd.DataFrame({"cik": [1], "month": ["2016-08-31"], "ocf": [None], "capex": [None], "fcf_end": [None],
                       "shares_out": [100.0], "shares_diluted": [100.0], "total_assets": [1000.0],
                       "close_raw": [10.0], "adjclose": [10.0], "foreign_form": [False]})
    assert b5.h1_velocity(df)["fcf"].isna().all()


# ---------- S2a: stale gross profit (item 2) ----------

def s2a_row(**kw):
    base = {"month": "2016-08-31", "gross_profit": 300.0, "gp_end": "2016-06-30", "revenue": 1000.0,
            "cost_of_revenue": 600.0, "rev_end": "2016-06-30", "cor_end": "2016-06-30", "rev_conflict": False, "cor_restated": False,
            "foreign_form": False, "total_assets": 1000.0}
    base.update(kw)
    return pd.DataFrame([base])


def test_s2a_rejects_stale_gross_profit_and_falls_back_only_to_fresh_revenue_minus_cost():
    assert b5.s2a_profitability(s2a_row()).iloc[0] == pytest.approx(0.3)  # fresh GrossProfit tag
    stale = s2a_row(gp_end="2015-12-31", gross_profit=900.0)  # 244 days old: never used
    assert b5.s2a_profitability(stale).iloc[0] == pytest.approx(0.4)  # fallback 1000 - 600
    both_stale = s2a_row(gp_end="2015-12-31", rev_end="2015-12-31", cor_end="2015-12-31")
    assert math.isnan(b5.s2a_profitability(both_stale).iloc[0])
    ends_differ = s2a_row(gross_profit=np.nan, cor_end="2016-03-31")
    assert math.isnan(b5.s2a_profitability(ends_differ).iloc[0])


# ---------- S2a: revenue-concept rule (item 1, ADDENDUM_1 §1) ----------

def partial_revenues(true=18_000, partial=2_000):
    """General Mills shape: 'Revenues' (ranked first) holds a partial line; a lower-ranked concept holds sales."""
    return (year_and_ytd("revenue", partial, partial / 2, partial / 2, "Revenues")
            + year_and_ytd("revenue", true, true / 2, true / 2, "RevenueFromContractWithCustomerExcludingAssessedTax"))


def test_partial_line_revenue_ranked_first_is_flagged_and_its_fallback_is_unavailable():
    rows = partial_revenues()
    sel = bi.ttm_input(rows, "2016-08-31")
    assert sel["concepts"] == ["Revenues"] and sel["val"] == 2_000  # panel.ttm picks the partial line
    rc = bi.revenue_check(rows, "2016-08-31", sel)
    assert rc["conflict"] and rc["worst_ratio"] == pytest.approx(9.0)
    f = s2a_row(gross_profit=np.nan, revenue=2_000.0, cost_of_revenue=12_000.0, rev_conflict=True)
    assert math.isnan(b5.s2a_profitability(f).iloc[0])


def test_gross_profit_tag_is_not_affected_by_a_revenue_conflict():
    assert b5.s2a_profitability(s2a_row(rev_conflict=True)).iloc[0] == pytest.approx(0.3)


def test_small_differences_between_revenue_concepts_are_not_conflicts():
    rows = partial_revenues(true=10_900, partial=10_000)  # 9% apart: under REV_CONFLICT
    rc = bi.revenue_check(rows, "2016-08-31", bi.ttm_input(rows, "2016-08-31"))
    assert not rc["conflict"] and rc["worst_ratio"] == pytest.approx(1.09)
    rows = partial_revenues(true=11_100, partial=10_000)  # 11% apart
    assert bi.revenue_check(rows, "2016-08-31", bi.ttm_input(rows, "2016-08-31"))["conflict"]


def test_zero_or_negative_selected_revenue_is_a_conflict():
    rows = year_and_ytd("revenue", -400, 10, 5, "Revenues") + year_and_ytd("revenue", 20_000, 10_000, 9_000, "SalesRevenueNet")
    rc = bi.revenue_check(rows, "2016-08-31", bi.ttm_input(rows, "2016-08-31"))
    assert rc["conflict"] and rc["worst_ratio"] == float("inf")


def test_a_conflict_in_any_combined_period_counts_and_only_known_filings_are_compared():
    rows = year_and_ytd("revenue", 18_000, 9_000, 8_500, "Revenues")
    rows.append(fact("revenue", "2016-01-01", "2016-06-30", 30_000, "2016-08-05", "SalesRevenueNet", "10-Q"))
    rc = bi.revenue_check(rows, "2016-08-31", bi.ttm_input(rows, "2016-08-31"))
    assert rc["conflict"]  # the year-to-date part conflicts even though the fiscal year does not
    late = year_and_ytd("revenue", 18_000, 9_000, 8_500, "Revenues")
    late.append(fact("revenue", "2016-01-01", "2016-06-30", 30_000, "2017-08-05", "SalesRevenueNet", "10-Q"))
    assert not bi.revenue_check(late, "2016-08-31", bi.ttm_input(late, "2016-08-31"))["conflict"]


def test_missing_conflict_flag_fails_closed():
    assert math.isnan(b5.s2a_profitability(s2a_row(gross_profit=np.nan, rev_conflict=None)).iloc[0])
    with pytest.raises(KeyError):
        b5.s2a_profitability(s2a_row().drop(columns="rev_conflict"))


# ---------- foreign-form rule (ADDENDUM_1 §3) ----------

def test_foreign_form_balance_sheet_makes_both_scores_unavailable():
    ta = [fact("total_assets", "", "2015-12-31", 5_000, "2016-03-01", form="40-F")]
    assert bi.foreign_form(ta, "2016-08-31") is True
    ta.append(fact("total_assets", "", "2016-06-30", 5_100, "2016-08-05", form="10-Q"))
    assert bi.foreign_form(ta, "2016-08-31") is False and bi.foreign_form(ta, "2016-07-31") is True
    assert bi.foreign_form([], "2016-08-31") is None
    assert math.isnan(b5.s2a_profitability(s2a_row(foreign_form=True)).iloc[0])
    assert math.isnan(b5.s2a_profitability(s2a_row(foreign_form=None)).iloc[0])  # unknown: fail closed


def test_company_month_returns_every_input_with_its_own_end():
    fx = {"ocf": year_and_ytd("ocf", 100, 60, 50), "capex": [fact("capex", "2015-01-01", "2015-12-31", 20, "2016-02-20")],
          "gross_profit": [fact("gross_profit", "2015-01-01", "2015-12-31", 300, "2016-02-20")],
          "revenue": partial_revenues(), "cost_of_revenue": year_and_ytd("cost_of_revenue", 12_000, 6_000, 6_000),
          "total_assets": [fact("total_assets", "", "2016-06-30", 50_000, "2016-08-05", form="10-Q")]}
    c = bi.company_month(fx, "2016-08-31")
    assert c["fcf_end"] is None and (c["ocf_end"], c["capex_end"]) == ("2016-06-30", "2015-12-31")
    assert (c["gp_end"], c["rev_end"], c["cor_end"]) == ("2015-12-31", "2016-06-30", "2016-06-30")
    assert c["rev_conflict"] is True and c["foreign_form"] is False
    row = pd.DataFrame([{**c, "month": "2016-08-31", "total_assets": 50_000.0}])
    assert math.isnan(b5.s2a_profitability(row).iloc[0])  # GP stale (244 days), fallback conflicts: no score


# ---------- ADDENDUM_2 §1-§2: the three revenue tests and the restated-period test ----------

def test_t1_compares_only_concepts_from_the_same_filing():
    """A larger value of another concept for the same period counts only when the same filing reported it."""
    rows = [fact("revenue", "2015-01-01", "2015-12-31", 2_000, "2016-02-20", "Revenues"),
            fact("revenue", "2015-01-01", "2015-12-31", 18_000, "2016-02-20", "SalesRevenueNet")]
    sel = bi.ttm_input(rows, "2016-03-31")
    assert bi.revenue_check(rows, "2016-03-31", sel)["reasons"] == ["T1"]
    other_filing = [rows[0], fact("revenue", "2015-01-01", "2015-12-31", 18_000, "2016-03-01", "SalesRevenueNet",
                                  accn="AMENDED")]
    # an annual figure in a different filing is not a concept conflict (and a lone fiscal year cannot mix bases)
    assert bi.revenue_check(other_filing, "2016-03-31", bi.ttm_input(other_filing, "2016-03-31"))["reasons"] == []


def test_t1_ignores_revenue_including_assessed_taxes():
    rows = [fact("revenue", "2015-01-01", "2015-12-31", 10_000, "2016-02-20", "Revenues"),
            fact("revenue", "2015-01-01", "2015-12-31", 13_000, "2016-02-20",
                 "RevenueFromContractWithCustomerIncludingAssessedTax")]  # excise taxes: a legitimate difference
    assert bi.revenue_check(rows, "2016-03-31", bi.ttm_input(rows, "2016-03-31"))["conflict"] is False


def spin_off(fy_recast_prior_year: bool, concept_after="Revenues"):
    """FY2015 annual report (old basis: 100), then a spin-off: the 2016 10-Q reports H1 2016 = 30 and recasts
    H1 2015 from 50 to 25. If `fy_recast_prior_year`, the FY2015 report itself already recast FY2014 (the
    separation happened before it), so FY2015 is on the new basis too."""
    rows = [fact("revenue", "2015-01-01", "2015-12-31", 100 if not fy_recast_prior_year else 50, "2016-02-20"),
            fact("revenue", "2014-01-01", "2014-12-31", 95 if not fy_recast_prior_year else 48, "2016-02-20"),
            fact("revenue", "2014-01-01", "2014-12-31", 95, "2015-02-20", accn="FY14"),
            fact("revenue", "2015-01-01", "2015-06-30", 50, "2015-08-05", form="10-Q"),
            fact("revenue", "2016-01-01", "2016-06-30", 30, "2016-08-05", concept_after, "10-Q"),
            fact("revenue", "2015-01-01", "2015-06-30", 25, "2016-08-05", concept_after, "10-Q")]
    return rows


def test_t2_flags_a_ttm_that_mixes_an_old_basis_year_with_recast_quarters():
    rows = spin_off(fy_recast_prior_year=False)
    sel = bi.ttm_input(rows, "2016-08-31")
    assert sel["val"] == 100 + 30 - 25  # 105: old-basis year plus new-basis change
    r = bi.restated_check(rows, "2016-08-31", sel)
    assert r["restated"] and r["worst_ratio"] == pytest.approx(2.0)
    assert bi.revenue_check(rows, "2016-08-31", sel)["reasons"] == ["T2"]
    assert not bi.restated_check(rows, "2016-03-31", bi.ttm_input(rows, "2016-03-31"))["restated"]  # before the recast


def test_t2_does_not_flag_when_the_year_is_already_on_the_new_basis():
    rows = spin_off(fy_recast_prior_year=True)
    sel = bi.ttm_input(rows, "2016-08-31")
    assert sel["val"] == 50 + 30 - 25 and not bi.restated_check(rows, "2016-08-31", sel)["restated"]


def test_t2_sees_a_recast_that_changes_the_concept():
    rows = spin_off(fy_recast_prior_year=False, concept_after="RevenueFromContractWithCustomerExcludingAssessedTax")
    assert bi.restated_check(rows, "2016-08-31", bi.ttm_input(rows, "2016-08-31"))["restated"]


def test_t0_non_positive_revenue_fails():
    rows = [fact("revenue", "2015-01-01", "2015-12-31", 0, "2016-02-20")]
    assert bi.revenue_check(rows, "2016-03-31", bi.ttm_input(rows, "2016-03-31"))["reasons"] == ["T0"]


def test_restated_cost_of_revenue_blocks_the_fallback_but_not_the_gross_profit_tag():
    assert math.isnan(b5.s2a_profitability(s2a_row(gross_profit=np.nan, cor_restated=True)).iloc[0])
    assert b5.s2a_profitability(s2a_row(cor_restated=True)).iloc[0] == pytest.approx(0.3)
    assert math.isnan(b5.s2a_profitability(s2a_row(gross_profit=np.nan, cor_restated=None)).iloc[0])
