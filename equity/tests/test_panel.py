"""Stage 1: point-in-time research panel from SEC bulk XBRL."""
import io
import json
import zipfile

from equity import panel


def fact(start, end, val, filed, form="10-Q", fp="Q1"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "fp": fp, "accn": f"a-{filed}"}


def company(cik=1, revenue=(), shares=(), extra=None):
    f = {"us-gaap": {"Revenues": {"units": {"USD": list(revenue)}}},
         "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": list(shares)}}}}
    if extra:
        f["us-gaap"].update(extra)
    return {"cik": cik, "entityName": "X", "facts": f}


def test_restatement_is_a_second_row_with_its_own_filing_date():
    rev = [fact("2020-01-01", "2020-12-31", 100, "2021-02-20", "10-K", "FY"),
           fact("2020-01-01", "2020-12-31", 100, "2022-02-20", "10-K", "FY"),  # re-reported, same value
           fact("2020-01-01", "2020-12-31", 90, "2022-06-01", "10-K/A", "FY")]  # restated
    rows = panel.extract_company(company(revenue=rev))
    r = [x for x in rows if x["metric"] == "revenue"]
    assert [(x["val"], x["filed"]) for x in r] == [(100, "2021-02-20"), (90, "2022-06-01")]
    assert panel.ttm(r, "2021-12-31")["val"] == 100  # restatement not yet public
    assert panel.ttm(r, "2022-12-31")["val"] == 90


def test_ttm_uses_fiscal_year_plus_ytd_minus_prior_ytd():
    rev = [fact("2020-01-01", "2020-12-31", 400, "2021-02-20", "10-K", "FY"),
           fact("2020-01-01", "2020-06-30", 190, "2020-08-01", "10-Q", "Q2"),
           fact("2021-01-01", "2021-06-30", 250, "2021-08-01", "10-Q", "Q2")]
    r = panel.extract_company(company(revenue=rev))
    assert panel.ttm(r, "2021-07-31") == {"val": 400, "end": "2020-12-31", "filed": "2021-02-20", "basis": "fy"}
    t = panel.ttm(r, "2021-08-02")
    assert t["val"] == 400 + 250 - 190 and t["end"] == "2021-06-30" and t["basis"] == "fy+ytd-prior_ytd"


def test_nothing_before_first_filing_and_forms_filtered():
    rev = [fact("2020-01-01", "2020-12-31", 400, "2021-02-20", "8-K", "FY")]
    assert panel.extract_company(company(revenue=rev)) == []
    rev = [fact("2020-01-01", "2020-12-31", 400, "2021-02-20", "10-K", "FY")]
    r = panel.extract_company(company(revenue=rev))
    assert panel.ttm(r, "2021-02-19") is None


def test_latest_instant_and_concept_fallback_rank():
    shares = [{"end": "2021-01-31", "val": 1000, "filed": "2021-02-20", "form": "10-K", "fp": "FY"},
              {"end": "2021-04-30", "val": 1100, "filed": "2021-05-05", "form": "10-Q", "fp": "Q1"}]
    rows = panel.extract_company(company(shares=shares))
    s = [x for x in rows if x["metric"] == "shares_out"]
    assert panel.latest(s, "2021-03-01")["val"] == 1000
    assert panel.latest(s, "2021-06-01")["val"] == 1100
    # Revenues (rank 0) beats SalesRevenueNet (rank 4) for the same period.
    extra = {"SalesRevenueNet": {"units": {"USD": [fact("2020-01-01", "2020-12-31", 999, "2021-02-20", "10-K", "FY")]}}}
    rev = [fact("2020-01-01", "2020-12-31", 400, "2021-02-20", "10-K", "FY")]
    rows = [x for x in panel.extract_company(company(revenue=rev, extra=extra)) if x["metric"] == "revenue"]
    assert panel.ttm(rows, "2021-03-01")["val"] == 400


def test_build_streams_zip_and_round_trips(tmp_path):
    zp = tmp_path / "cf.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("CIK0000000001.json", json.dumps(company(1, [fact("2020-01-01", "2020-12-31", 5, "2021-01-05", "10-K", "FY")])))
        z.writestr("CIK0000000002.json", json.dumps({"cik": 2, "facts": {}}))
        z.writestr("CIK0000000003.json", "{not json")
        z.writestr("CIK0000000004.json", json.dumps({**company(0, [fact("2020-01-01", "2020-12-31", 7, "2021-01-05", "10-K", "FY")]), "cik": ""}))
    out = tmp_path / "p.csv.gz"
    st = panel.build(zp, out, log=None)
    assert st == {"companies": 4, "with_rows": 2, "rows": 2, "bad_json": 1}
    rows = list(panel.read(out))
    assert rows[0]["cik"] == 1 and rows[0]["val"] == 5.0 and rows[0]["metric"] == "revenue"
    assert rows[1]["cik"] == 4  # empty cik field filled from the file name
    assert list(panel.read(out, ciks={2})) == []
    assert "cik,metric" in panel.write_rows(rows)
    assert io  # imported for helpers


def test_company_record_tracks_periodic_and_deregistration_dates():
    sub = {"cik": "0000000042", "name": "Gone Inc", "entityType": "operating", "sic": "3674", "sicDescription": "Semis",
           "tickers": [], "exchanges": [], "formerNames": [{"name": "Old Gone"}],
           "filings": {"recent": {"form": ["15-12G", "10-Q", "8-K"], "filingDate": ["2019-03-01", "2018-11-05", "2018-12-01"]},
                       "files": [{"name": "CIK0000000042-submissions-001.json"}]}}
    older = [{"form": ["10-K", "S-1"], "filingDate": ["2012-03-01", "2011-01-01"]}]
    r = panel.company_record(sub, older)
    assert r["cik"] == 42 and r["first_periodic"] == "2012-03-01" and r["last_periodic"] == "2018-11-05"
    assert r["deregistered"] == "2019-03-01" and r["tickers"] == "" and r["former_names"] == "Old Gone"
