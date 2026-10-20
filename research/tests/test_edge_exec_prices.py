"""B1 execution-price dataset: cutoff, first-trading-day selection, statuses, FX fallback, integrity checks."""
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_exec_prices as ep  # noqa: E402
import edge_rules  # noqa: E402
import edge_split  # noqa: E402


def chart(dates, closes, adj=None, currency="USD", gmtoffset=-18000):
    """A Yahoo chart response with bars at 14:30 UTC (09:30 New York)."""
    ts = [int((pd.Timestamp(d) + pd.Timedelta(hours=14, minutes=30)).tz_localize("UTC").timestamp()) for d in dates]
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": currency, "gmtoffset": gmtoffset}, "timestamp": ts,
        "indicators": {"quote": [{"close": closes}], "adjclose": [{"adjclose": adj or closes}]}}]}}).encode()


def bdays(a, b, holidays=()):
    return pd.DatetimeIndex([d for d in pd.bdate_range(a, b) if d not in set(pd.to_datetime(list(holidays)))])


CAL = bdays("2021-11-01", "2022-12-30", holidays=["2022-01-17", "2022-05-30", "2022-07-04", "2022-01-03"])


def daily(dates, price=10.0):
    return pd.DataFrame({"close": price, "adjclose": price}, index=pd.DatetimeIndex(dates))


def test_requests_end_before_2023():
    q = parse_qs(urlparse(ep.chart_url("AAPL")).query)
    assert pd.Timestamp(int(q["period2"][0]), unit="s") <= pd.Timestamp("2023-01-01")
    q = parse_qs(urlparse(ep.fred_url("DEXUSUK")).query)
    assert q["coed"] == ["2022-12-31"]


def test_parse_daily_drops_and_checks_post_cutoff_bars():
    d = ep.parse_daily(chart(["2022-12-29", "2022-12-30", "2023-01-03"], [1.0, 2.0, 3.0]))
    assert d.index.max() == pd.Timestamp("2022-12-30")
    assert list(d.index) == [pd.Timestamp("2022-12-29"), pd.Timestamp("2022-12-30")]  # exchange-local dates
    with pytest.raises(edge_split.HoldoutViolation):
        ep.assert_cut([pd.Timestamp("2023-01-03")], "x")


def test_first_trading_day_after_month_end_handles_weekends_and_holidays():
    # 2022-04-30 is a Saturday: the decision close is Friday 29 April, execution Monday 2 May.
    assert ep.calendar_dates(CAL, pd.Timestamp("2022-04-30")) == (pd.Timestamp("2022-04-29"), pd.Timestamp("2022-05-02"))
    # 2021-12-31 is a Friday; 3 January is (in this synthetic calendar) a holiday, so execution is 4 January.
    assert ep.calendar_dates(CAL, pd.Timestamp("2021-12-31"))[1] == pd.Timestamp("2022-01-04")
    # Never before edge_rules' business-day convention, and strictly after the decision.
    for m in pd.date_range("2021-12-31", "2022-11-30", freq="ME"):
        ex = ep.calendar_dates(CAL, m)[1]
        assert ex >= edge_rules.execution_time(m) and ex > m


def test_company_rows_statuses():
    months = [pd.Timestamp("2022-04-30"), pd.Timestamp("2022-05-31"), pd.Timestamp("2022-06-30"),
              pd.Timestamp("2022-07-31"), pd.Timestamp("2022-08-31")]
    dates = [d for d in CAL if d >= pd.Timestamp("2022-04-01")]
    d = daily(dates)
    d = d.drop(pd.Timestamp("2022-06-01"))  # no trade on May's execution day -> missing_exec
    d = d.drop(pd.Timestamp("2022-06-30"))  # last June close is 29 June -> stale_month_end
    d.loc[pd.Timestamp("2022-07-29"), "adjclose"] = -1.0  # invalid decision close
    d = d[(d.index < pd.Timestamp("2022-08-01")) | (d.index > pd.Timestamp("2022-08-31"))]  # no August bars
    rows = {r["month"]: r for r in ep.company_rows(d, CAL, 1, "X", months)}
    assert rows["2022-04-30"]["status"] == "ok" and rows["2022-04-30"]["exec_date"] == "2022-05-02"
    assert rows["2022-05-31"]["status"] == "missing_exec" and pd.isna(rows["2022-05-31"]["exec_adjclose"])
    assert rows["2022-06-30"]["status"] == "stale_month_end" and rows["2022-06-30"]["me_date"] == "2022-06-29"
    assert rows["2022-07-31"]["status"] == "invalid_price"
    assert "2022-08-31" not in rows


def test_no_decision_executes_after_the_cutoff():
    assert ep.decision_months()[-1] == pd.Timestamp("2022-11-30")
    with pytest.raises(edge_split.HoldoutViolation):
        ep.company_rows(daily(CAL), CAL, 1, "X", [pd.Timestamp("2022-12-31")])
    with pytest.raises(edge_split.HoldoutViolation):
        ep.company_rows(daily(list(CAL) + [pd.Timestamp("2023-01-03")]), CAL, 1, "X", [pd.Timestamp("2022-11-30")])


def test_execution_columns_cannot_reach_a_decision():
    panel = pd.DataFrame({"cik": [1], "month": ["2022-04-30"], "me_adjclose": [10.0], "exec_adjclose": [11.0],
                          "exec_close": [11.0], "exec_date": ["2022-05-02"]})
    assert not any(c.startswith("exec_") for c in edge_rules.decision_frame(panel, "2022-04-30").columns)


def _fake_get(fred_body=None, yahoo_body=None):
    def get(url):
        if "fred" in url:
            if fred_body is None:
                raise RuntimeError("FRED unreachable")
            return fred_body
        if yahoo_body is None:
            raise RuntimeError("Yahoo unreachable")
        return yahoo_body
    return get


def test_fx_falls_back_to_yahoo_and_records_source():
    yb = chart(["2022-11-29", "2022-11-30"], [1.19, 1.20], currency="USD", gmtoffset=0)
    fx = ep.gbpusd(_fake_get(None, yb))
    assert set(fx["source"]) == {"Yahoo:GBPUSD=X"} and fx["usd_per_gbp"].iloc[-1] == 1.20
    fb = b"DATE,DEXUSUK\n2022-11-29,1.18\n2022-11-30,.\n2023-01-03,1.21\n"
    fx = ep.gbpusd(_fake_get(fb, yb))
    assert fx.loc["2022-11-29", "source"] == "FRED:DEXUSUK" and fx.loc["2022-11-29", "usd_per_gbp"] == 1.18
    assert fx.loc["2022-11-30", "source"] == "Yahoo:GBPUSD=X"  # FRED gap filled from Yahoo
    assert fx.index.max() <= ep.CUTOFF  # FRED's 2023 row dropped
    with pytest.raises(RuntimeError):
        ep.gbpusd(_fake_get(None, None))


def test_benchmarks_convert_pence():
    body = chart(["2022-11-30"], [8000.0], currency="GBp", gmtoffset=0)
    b = ep.benchmarks(lambda url: body)
    assert b["VWRP"].iloc[0] == 80.0


def _good_rows():
    rows = []
    for cik in (1, 2):
        rows += ep.company_rows(daily([d for d in CAL if d >= pd.Timestamp("2022-01-01")]), CAL, cik, f"T{cik}",
                                [m for m in ep.decision_months() if m >= pd.Timestamp("2022-01-31")])
    return pd.DataFrame(rows, columns=ep.FIELDS)


def test_integrity_checks(monkeypatch):
    months = [m for m in ep.decision_months() if m >= pd.Timestamp("2022-01-31")]
    monkeypatch.setattr(ep, "decision_months", lambda: months)
    rows = _good_rows()
    st = {c["check"]: c["status"] for c in ep.check(rows, CAL)}
    assert "FAIL" not in st.values()
    dup = pd.concat([rows, rows.iloc[[0]]])
    assert {c["check"]: c["status"] for c in ep.check(dup, CAL)}["one row per company-month"] == "FAIL"
    late = rows.copy()
    late.loc[0, "exec_date"] = "2023-01-03"
    st = {c["check"]: c["status"] for c in ep.check(late, CAL)}
    assert st["strict cutoff: no date after 2022-12-31"] == "FAIL"
    wrong = rows.copy()
    wrong.loc[0, "exec_date"] = wrong.loc[0, "month"]  # traded at the decision close
    st = {c["check"]: c["status"] for c in ep.check(wrong, CAL)}
    assert st["execution date is the first US trading day after the month-end"] == "FAIL"
    neg = rows.copy()
    neg.loc[0, "exec_adjclose"] = -5.0
    assert {c["check"]: c["status"] for c in ep.check(neg, CAL)}["usable rows have positive prices"] == "FAIL"


def test_load_refuses_a_modified_file(tmp_path):
    rows = _good_rows()
    p = tmp_path / "exec_prices_to_2022.csv.gz"
    rows.to_csv(p, index=False)
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {p.name: {"sha256": ep._sha(p), "rows": len(rows)}}}))
    assert len(ep.load(tmp_path)) == len(rows)
    rows.iloc[:5].to_csv(p, index=False)
    with pytest.raises(RuntimeError):
        ep.load(tmp_path)


def test_return_agreement_check_compares_consecutive_months(monkeypatch):
    months = [m for m in ep.decision_months() if m >= pd.Timestamp("2022-01-31")]
    monkeypatch.setattr(ep, "decision_months", lambda: months)
    rows = _good_rows()
    monthly = rows[["cik", "month"]].assign(adjclose=10.0, currency="USD")
    st = {c["check"]: c for c in ep.check(rows, CAL, monthly)}
    c = st["month-end returns agree with the research dataset (within 0.1 points)"]
    assert c["status"] == "PASS" and "of 20 monthly" in c["detail"]
    monthly.loc[monthly.index[3], "adjclose"] = 12.0
    assert ep.check(rows, CAL, monthly)[-1]["status"] == "WARN"
