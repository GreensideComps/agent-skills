"""Synthetic tests for the B5 building blocks (edge_b5). No research data is read."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_b5 as b5  # noqa: E402

MONTHS = pd.date_range("2012-01-31", "2016-12-31", freq="ME")


def company(cik=1, fps=lambda yrs: 1.0 + 0.0 * yrs, shares=lambda m: 100.0, assets=1000.0, price=50.0,
            split_at=None, div_drift=0.0, financial=False):
    """One company, month-end rows. TTM FCF per share at a quarter-end period is fps(years since 2010); a row's
    TTM is the latest quarter-end at least 2 months before the month-end (as if filed with a lag)."""
    rows = []
    for m in MONTHS:
        q_end = (m - pd.offsets.MonthEnd(2)) - pd.offsets.QuarterEnd(0)
        if q_end > m - pd.offsets.MonthEnd(2):
            q_end = q_end - pd.offsets.QuarterEnd(1)
        yrs = q_end.year - 2010 + q_end.month / 12  # exact quarters, so linear growth is exactly linear
        sh = shares(m)
        split = 2.0 if split_at is not None and m >= pd.Timestamp(split_at) else 1.0
        fcf = fps(yrs) * sh
        rows.append({"cik": cik, "month": m, "ocf": fcf + 10.0, "capex": 10.0, "fcf_end": str(q_end.date()),
                     "shares_out": sh * split, "shares_diluted": sh * split, "total_assets": assets,
                     "close_raw": price / split, "adjclose": price / 2.0 * (1 + div_drift) ** ((m - MONTHS[0]).days / 365.25),
                     "financial": financial, "foreign_form": False, "mcap": sh * split * price / split,
                     "ocf_restated": False, "capex_restated": False})
    return pd.DataFrame(rows)


def at(df, score, month="2016-06-30"):
    return float(score[df["month"] == pd.Timestamp(month)].iloc[0])


def test_constant_growth_scores_zero_acceleration_positive_deceleration_negative():
    lin = company(fps=lambda y: 1.0 + 0.2 * y)
    acc = company(cik=2, fps=lambda y: 1.0 + 0.05 * y * y)
    dec = company(cik=3, fps=lambda y: 1.0 + 2.0 * math.sqrt(y))
    assert at(lin, b5.h1_score(lin)) == pytest.approx(0.0, abs=1e-12)
    assert at(acc, b5.h1_score(acc)) > 0
    assert at(dec, b5.h1_score(dec)) < 0


def test_foreign_form_rows_have_no_h1_score_under_rule_a(monkeypatch):
    """ADDENDUM_1 §3 (rule A, kept for the comparison): a row whose latest balance sheet came from a 20-F/40-F, or whose form is unknown, has no G;
    so neither it nor a score that needs it 12 months later exists."""
    monkeypatch.setattr(b5, "IDENTITY_RULE", "A")
    acc = company(fps=lambda y: 1.0 + 0.05 * y * y)
    assert not math.isnan(at(acc, b5.h1_score(acc)))
    for flag in (True, None):
        f = acc.copy()
        f["foreign_form"] = f["foreign_form"].astype(object)
        f.loc[f["month"] == pd.Timestamp("2015-06-30"), "foreign_form"] = flag
        assert math.isnan(at(f, b5.h1_score(f)))  # G at t-12 missing
        assert math.isnan(at(f, b5.h1_score(f), "2015-06-30"))


def test_identity_rule_options_a_b_c():
    """ADDENDUM_2 §3: A drops foreign-form rows, B drops CIK 1635327 only, C drops CIK 1635327 and any row with a
    market cap above 100 x total assets. C is in force (owner, 14:17Z)."""
    df = pd.DataFrame({"cik": [1635327, 1, 2, 3, 4], "foreign_form": [True, True, False, False, None],
                       "mcap": [16e9, 15e9, 20e9, 30e9, None], "total_assets": [11e9, 0.05e9, 0.1e9, 0.3e9, 5e9]})
    assert b5.IDENTITY_RULE == "C"
    assert b5.identity_ok(df, "A").tolist() == [False, False, True, True, False]
    assert b5.identity_ok(df, "B").tolist() == [False, True, True, True, True]
    assert b5.identity_ok(df, "C").tolist() == [False, False, False, True, True]  # 300x and 200x out; exactly 100x kept
    with pytest.raises(ValueError):
        b5.identity_ok(df, "D")
    with pytest.raises(KeyError):
        b5.identity_ok(df.drop(columns="mcap"), "C")  # fails closed: the input C needs is missing


def test_rule_c_strict_threshold_and_missing_assets():
    """ADDENDUM_2 §3 rule C: strictly greater than 100x fails; exactly 100x passes; missing, zero or negative total
    assets and missing mcap leave the ratio undefined, so rule C passes the row (it has no score anyway, below)."""
    df = pd.DataFrame({"cik": [1] * 7, "mcap": [100e9, 100.0001e9, 1e12, 1e12, 1e12, np.nan, 2.3e13],
                       "total_assets": [1e9, 1e9, np.nan, 0.0, -5e9, 1e9, 1e7]})
    assert b5.identity_ok(df, "C").tolist() == [True, False, True, True, True, True, False]


def test_rule_c_regression_cases_from_the_input_audit():
    """Values from b5_input_audit.md: Medtronic 2015 (assets at the wrong scale, 2.3 million x) and Atlas Lithium
    fail; Zoom at its 54x peak, Atlassian 39x and the residual Curis 97x / BeOne 97x pass (disclosed residual risk);
    The Stars Group's CIK fails at 2.2x."""
    df = pd.DataFrame({"cik": [1613103, 1540684, 1585521, 1650372, 1108205, 1651308, 1635327],
                       "mcap": [2306440 * 46e3, 8149 * 1e6, 54 * 1e9, 39 * 1e9, 97 * 1e8, 97 * 1e8, 2.2 * 11e9],
                       "total_assets": [46e3, 1e6, 1e9, 1e9, 1e8, 1e8, 11e9]})
    assert b5.identity_ok(df, "C").tolist() == [False, False, True, True, True, True, False]


def test_rule_c_and_t2_flags_remove_h1_inputs():
    """Rule C (mcap > 100 x assets at t-12) and T2 on ocf or capex (at t or t-12) remove G, so the score is missing;
    a missing T2 flag fails closed."""
    acc = company(fps=lambda y: 1.0 + 0.05 * y * y)
    assert not math.isnan(at(acc, b5.h1_score(acc)))
    t12 = acc["month"] == pd.Timestamp("2015-06-30")
    for col, val in (("mcap", 1e12), ("ocf_restated", True), ("capex_restated", True), ("ocf_restated", None)):
        f = acc.copy()
        f[col] = f[col].astype(object)
        f.loc[t12, col] = val
        assert math.isnan(at(f, b5.h1_score(f))), col


def test_score_matches_a_hand_calculation():
    df = company(fps=lambda y: 1.0 + 0.05 * y * y, assets=2000.0)
    s = b5.h1_score(df)
    i = df.index[df["month"] == pd.Timestamp("2016-06-30")][0]
    e = pd.Timestamp(df.loc[i, "fcf_end"])
    y = lambda d: d.year - 2010 + d.month / 12  # noqa: E731
    f = lambda d: (1.0 + 0.05 * y(d) ** 2) * 100.0  # noqa: E731  FCF (shares constant at 100, q = 1)
    e12 = pd.Timestamp(df.loc[df["month"] == pd.Timestamp("2015-06-30"), "fcf_end"].iloc[0])
    e24 = pd.Timestamp(df.loc[df["month"] == pd.Timestamp("2014-06-30"), "fcf_end"].iloc[0])
    expect = (f(e) - f(e12)) / 2000.0 - (f(e12) - f(e24)) / 2000.0
    assert s[i] == pytest.approx(expect, rel=1e-12)


def test_split_between_years_does_not_change_the_score():
    base = company(fps=lambda y: 1.0 + 0.05 * y * y)
    split = company(fps=lambda y: 1.0 + 0.05 * y * y, split_at="2015-12-31")
    a, b = b5.h1_score(base), b5.h1_score(split)
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_dividend_drift_in_adjclose_is_not_read_as_a_split():
    d = company(div_drift=0.05)
    v = b5.h1_velocity(d)
    assert (v["s"].dropna() == 1.0).all()


def test_buyback_raises_per_share_velocity():
    bb = company(shares=lambda m: 100.0 * (0.9 if m >= pd.Timestamp("2015-12-31") else 1.0))
    v = b5.h1_velocity(bb)
    g = v.loc[v["month"] == pd.Timestamp("2016-06-30"), "G"].iloc[0]
    # FCF per share flat at 1.0; shares 100 -> 90 so q = 0.9: G = (90 - 0.9 x 100) / 1000 = 0 per-share change?
    # FCF = fps x shares: 90 now vs 100 a year ago, restated on today's shares 0.9 x 100 = 90: no per-share change.
    assert g == pytest.approx(0.0, abs=1e-12)
    flat_total = company(shares=lambda m: 100.0 * (0.9 if m >= pd.Timestamp("2015-12-31") else 1.0),
                         fps=lambda y: 1.0)
    flat_total["ocf"] = 110.0  # total FCF flat at 100 while shares fall 10%: per-share FCF rises
    v2 = b5.h1_velocity(flat_total)
    g2 = v2.loc[v2["month"] == pd.Timestamp("2016-06-30"), "G"].iloc[0]
    assert g2 == pytest.approx((100 - 0.9 * 100) / 1000.0, rel=1e-12)


def test_share_change_over_3x_without_a_split_is_missing():
    d = company(shares=lambda m: 100.0 * (4.0 if m >= pd.Timestamp("2016-03-31") else 1.0))
    assert math.isnan(at(d, b5.h1_score(d)))


def test_stale_or_mismatched_periods_are_missing():
    stale = company()
    stale.loc[stale["month"] == pd.Timestamp("2016-06-30"), "fcf_end"] = "2015-09-30"  # 274 days old
    assert math.isnan(at(stale, b5.h1_score(stale)))
    gap = company()
    gap.loc[gap["month"] == pd.Timestamp("2015-06-30"), "fcf_end"] = "2014-12-31"  # t-12 period 15 months back
    assert math.isnan(at(gap, b5.h1_score(gap)))
    mism = company()
    mism.loc[mism["month"] == pd.Timestamp("2016-06-30"), "fcf_end"] = None  # ocf and capex periods differ
    assert math.isnan(at(mism, b5.h1_score(mism)))


def test_capex_missing_means_no_score():
    d = company()
    d.loc[d["month"] == pd.Timestamp("2016-06-30"), "capex"] = np.nan
    assert math.isnan(at(d, b5.h1_score(d)))


def test_point_in_time_later_rows_do_not_change_earlier_scores():
    a = company(fps=lambda y: 1.0 + 0.05 * y * y)
    b = a.copy()
    later = b["month"] > pd.Timestamp("2016-06-30")
    b.loc[later, ["ocf", "total_assets", "shares_out", "close_raw"]] *= 7.0
    sa, sb = b5.h1_score(a), b5.h1_score(b)
    keep = ~later
    pd.testing.assert_series_equal(sa[keep], sb[keep])


def test_financials_have_no_score_and_index_is_preserved():
    d = pd.concat([company(cik=1), company(cik=2, financial=True)]).reset_index(drop=True)
    d = d.sample(frac=1.0, random_state=1)  # shuffled input order
    s = b5.h1_score(d)
    assert list(s.index) == list(d.index)
    assert s[d["cik"] == 2].isna().all() and s[(d["cik"] == 1) & (d["month"] >= "2015-03-31")].notna().any()


def test_s2a_profitability_uses_only_fresh_periods():
    f = pd.DataFrame({"month": ["2016-06-30"] * 3, "gross_profit": [300.0, np.nan, 300.0],
                      "gp_end": ["2016-03-31", None, "2015-09-30"], "revenue": [np.nan, 1000.0, np.nan],
                      "cost_of_revenue": [np.nan, 600.0, np.nan], "rev_end": [None, "2016-03-31", None],
                      "cor_end": [None, "2016-03-31", None], "total_assets": [1000.0, 2000.0, 1000.0],
                      "rev_conflict": [False] * 3, "cor_restated": [False] * 3, "gp_restated": [False] * 3,
                      "cik": [1, 2, 3], "mcap": [5e4] * 3})
    v = b5.s2a_profitability(f)
    assert v.iloc[0] == pytest.approx(0.3) and v.iloc[1] == pytest.approx(0.2) and math.isnan(v.iloc[2])


def test_s2a_score_ranks_within_group_without_financials():
    fr = pd.DataFrame({"gp_assets": [0.1, 0.3, 0.2, 0.9], "group": ["a", "a", "b", "finance"],
                       "financial": [False, False, False, True]})
    s = b5.s2a_score(fr)
    assert list(s[:3]) == [0.5, 1.0, 1.0] and math.isnan(s.iloc[3])


def test_tranches_combine_as_equal_capital_without_rebalancing():
    idx = pd.date_range("2015-02-02", periods=4, freq="MS")
    a = pd.Series([2.0, 2.2, 2.42, 2.662], index=idx)  # +10% a month
    b = pd.Series([5.0, 5.0, 5.0, 5.0], index=idx)
    c = b5.combine_tranches([a, b], idx[0])
    assert list(c.round(6)) == [1.0, 1.05, 1.105, 1.1655]
    with pytest.raises(ValueError):
        b5.combine_tranches([a, b.iloc[1:]], idx[0])


def test_placebo_is_fixed_and_uninformative():
    c = pd.Series([320193, 789019, 1018724])
    a, b = b5.placebo_score(c), b5.placebo_score(c)
    assert a.equals(b) and a.between(-1, 0).all() and a.nunique() == 3


def _good(**kw):
    r = {"trial": "H1", "t_nw": 3.5, "dsr": 0.85, "alpha": 0.02, "alpha_t": 2.5, "excess_2x": 0.01,
         "excess_vs_universe": 0.01, "excess_miss100": 0.01, "excess_nextmonth": 0.01, "excess_dataerr": 0.01,
         "excess_pitq": 0.01, "excess_thirds": [0.01, -0.01, 0.02], "excess_without_top_contributor": 0.01}
    r.update(kw)
    return r


@pytest.fixture
def check4_done(tmp_path):
    p = tmp_path / "status.json"
    p.write_text('{"ttm_check4_independent_source": {"complete": true}}')
    return p


def test_verdict_requires_every_gate_and_robustness_only_vetoes(check4_done):
    v = lambda r: b5.verdict(r, check4_done)  # noqa: E731  (as if the owner had recorded check 4 complete)
    assert v(_good())["label"] == "E2 candidate"
    assert v(_good(excess_miss100=-0.001))["label"] == "fail"  # one robustness check vetoes
    assert v(_good(dsr=0.79))["label"] == "fail"
    assert v(_good(t_nw=2.9, dsr=0.6))["label"] == "lead, not a pass"  # strong robustness cannot rescue
    assert v(_good(t_nw=2.9, excess_pitq=None))["label"] == "fail"  # missing input fails closed
    assert v(_good(trial="S2A"))["label"] == "fail"  # S2a also needs the non-overlapping t
    assert v(_good(trial="S2A", t_nonoverlap=2.1))["label"] == "E2 candidate"
    assert v(_good(excess_thirds=[0.01, -0.01, -0.02]))["label"] == "fail"


def test_open_check4_withholds_the_e2_label(tmp_path):
    """ADDENDUM_1 §6 (owner 13:03Z item 6): with check 4 open, as recorded now, no result can be labelled E2."""
    assert b5.check4_complete() is False  # the real status file
    r = b5.verdict(_good())
    assert all(r["checks"].values()) and r["label"] == b5.E2_BLOCKED_LABEL and "E2 candidate" not in r["label"]
    missing = tmp_path / "nope.json"
    assert b5.verdict(_good(), missing)["label"] == b5.E2_BLOCKED_LABEL  # unreadable status counts as open
    assert b5.verdict(_good(t_nw=2.5))["label"] == "lead, not a pass"  # other labels unchanged


def test_positive_return_alone_is_not_a_pass():
    r = _good(t_nw=1.0, dsr=0.1, alpha=0.001, alpha_t=0.3)
    assert b5.verdict(r)["label"] == "fail"


def test_newey_west_t_with_no_autocorrelation_is_close_to_the_simple_t():
    x = pd.Series(np.random.default_rng(3).normal(0.01, 0.05, 5000))
    simple = x.mean() / (x.std(ddof=0) / math.sqrt(len(x)))
    assert b5.newey_west_t(x, 3) == pytest.approx(simple, rel=0.05)
