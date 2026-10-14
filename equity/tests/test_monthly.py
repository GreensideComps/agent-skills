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
