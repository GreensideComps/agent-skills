"""Stage 1: monthly point-in-time company metrics."""
from equity import monthly, panel


def row(metric, start, end, val, filed, unit="USD", rank=0):
    return {"cik": 7, "metric": metric, "rank": rank, "taxonomy": "us-gaap", "concept": "c", "unit": unit,
            "start": start, "end": end, "val": val, "filed": filed, "form": "10-K", "fp": "FY", "accn": "a"}


def test_month_ends():
    assert monthly.month_ends("2020-11-30", "2021-02-28") == ["2020-11-30", "2020-12-31", "2021-01-31", "2021-02-28"]


def test_company_months_point_in_time_active_window_and_staleness():
    rows = [row("revenue", "2019-01-01", "2019-12-31", 100.0, "2020-02-15"),
            row("revenue", "2020-01-01", "2020-12-31", 120.0, "2021-02-15"),
            row("cash", "", "2020-12-31", 5.0, "2021-02-15"),
            row("revenue", "2020-01-01", "2020-12-31", 999.0, "2021-02-15", unit="EUR"),  # other currency ignored
            row("shares_out", "", "2021-02-01", 10.0, "2021-02-15", unit="shares")]
    months = monthly.month_ends("2020-01-31", "2023-12-31")
    out = {r["month"]: r for r in monthly.company_months(7, rows, months)}
    assert "2020-01-31" not in out  # nothing filed yet
    assert out["2020-02-29"]["ttm_revenue"] == 100.0 and out["2020-02-29"]["cash"] == ""
    assert out["2021-02-28"]["ttm_revenue"] == 120.0 and out["2021-02-28"]["cash"] == 5.0
    assert out["2021-02-28"]["shares_out"] == 10.0
    # stops appearing 15 months after its last filing (2021-02-15)
    assert "2022-05-31" in out and "2022-06-30" not in out
    # figures for periods that ended over 18 months ago are unknown, not carried forever
    assert out["2022-05-31"]["ttm_revenue"] == 120.0
    assert panel.ttm(rows[:2], "2022-12-31")["val"] == 120.0


def test_share_counts_filed_after_the_month_end_never_change_that_month():
    """Owner review 2026-10-19 item 1 (identity rule C): shares_out (cover page, instant) and shares_diluted
    (weighted average of the latest period) at a month-end use only facts filed on or before it. A late count, a
    restatement of an earlier period and an amendment, all filed afterwards, leave the month unchanged."""
    base = [row("revenue", "2015-01-01", "2015-12-31", 100.0, "2016-02-20"),
            row("shares_out", "", "2016-02-10", 10.0, "2016-02-20", unit="shares"),
            row("shares_diluted", "2015-01-01", "2015-12-31", 11.0, "2016-02-20", unit="shares"),
            row("total_assets", "", "2015-12-31", 1000.0, "2016-02-20")]
    later = [row("shares_out", "", "2016-02-10", 1e5, "2016-04-15", unit="shares"),  # amended cover count, same date
             row("shares_out", "", "2016-03-31", 2e5, "2016-05-05", unit="shares"),  # period ends before the month-end
             row("shares_diluted", "2015-01-01", "2015-12-31", 3e5, "2016-04-15", unit="shares"),  # restated
             row("shares_diluted", "2016-01-01", "2016-03-31", 4e5, "2016-05-05", unit="shares"),  # Q1, filed in May
             row("total_assets", "", "2016-03-31", 5e5, "2016-05-05")]
    months = monthly.month_ends("2016-01-31", "2016-06-30")
    pit = {r["month"]: r for r in monthly.company_months(7, base, months)}
    full = {r["month"]: r for r in monthly.company_months(7, base + later, months)}
    for mo in ("2016-02-29", "2016-03-31"):
        for f in ("shares_out", "shares_diluted", "total_assets"):
            assert full[mo][f] == pit[mo][f]
        assert (full[mo]["shares_out"], full[mo]["shares_diluted"]) == (10.0, 11.0)
    # each later fact is used from the month-end after its own filing date, not before
    assert (full["2016-04-30"]["shares_out"], full["2016-04-30"]["shares_diluted"]) == (1e5, 3e5)
    assert (full["2016-05-31"]["shares_out"], full["2016-05-31"]["shares_diluted"]) == (2e5, 4e5)
    assert full["2016-05-31"]["total_assets"] == 5e5
