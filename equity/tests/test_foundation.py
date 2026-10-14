"""Milestone 1 acceptance tests: ledgers, jobs, SEC client, security master,
fundamentals with provenance, pipeline transitions, snapshots and the search index."""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import INSTRUMENTS, SEC_TICKERS, make_facts

from equity import index, pipeline
from equity.fundamentals import analyse, cagr
from equity.ingest import ingest_company, resolve
from equity.jobs import JobSkipped, job, job_health
from equity.sec import FACTS_URL, TICKERS_URL, SecError, user_agent
from equity.store import Ledger
from equity.universe import build_security_master, sync_security_master

TODAY = date(2026, 10, 14)


# ---------------------------------------------------------------- ledgers
def test_ledger_dedupes_and_tolerates_torn_line(tmp_path):
    led = Ledger(tmp_path / "x.jsonl")
    assert led.append([{"rid": "a", "v": 1}, {"rid": "a", "v": 2}]) == 1
    assert led.append({"rid": "a", "v": 3}) == 0
    with led.path.open("a") as f:
        f.write('{"rid": "b", "v"')  # crashed mid-write
    assert [r["rid"] for r in led.read()] == ["a"]
    with pytest.raises(ValueError):
        led.append({"v": 1})


def test_union_merged_duplicate_lines_are_read_once(tmp_path):
    led = Ledger(tmp_path / "x.jsonl")
    led.path.write_text('{"rid":"a","v":1}\n{"rid":"a","v":1}\n')
    assert len(led.read()) == 1


# ---------------------------------------------------------------- jobs
def test_job_records_ok_failure_redaction_and_idempotency(store):
    with job(store, "j", {"x": 1}, idempotency_key="k1") as j:
        j["outputs"] = {"n": 5}
    with pytest.raises(JobSkipped):
        with job(store, "j", {}, idempotency_key="k1"):
            pass
    with job(store, "j", {}, idempotency_key="k1", force=True):
        pass
    with pytest.raises(RuntimeError):
        with job(store, "j2", {}, idempotency_key="k2", redact=["s3cr3t"]):
            raise RuntimeError("token s3cr3t rejected")
    finishes = [e for e in store.jobs.read() if e["event"] == "finish"]
    failed = [e for e in finishes if e["status"] == "failed"][0]
    assert "s3cr3t" not in json.dumps(failed) and "<redacted>" in failed["error"]
    # A failed key is not "completed": a retry runs.
    with job(store, "j2", {}, idempotency_key="k2"):
        pass
    h = job_health(store)
    assert set(h["last_ok"]) == {"j", "j2"} and h["stuck"] == []


def test_job_health_reports_stuck_runs(store):
    store.jobs.append({"rid": "r:start", "event": "start", "run_id": "r", "job": "slow",
                       "ts_utc": "2026-10-14T00:00:00+00:00"})
    h = job_health(store, now=datetime(2026, 10, 14, 3, tzinfo=timezone.utc))
    assert h["stuck"][0]["job"] == "slow"
    h = job_health(store, now=datetime(2026, 10, 14, 1, tzinfo=timezone.utc))
    assert h["stuck"] == []


# ---------------------------------------------------------------- SEC client
def test_user_agent_requires_contact_email():
    with pytest.raises(SecError):
        user_agent({"SEC_USER_AGENT": "my app"})
    assert user_agent({"SEC_USER_AGENT": "app a@b.co"}) == "app a@b.co"


def test_sec_client_retries_429_caches_and_paces(make_sec):
    facts, _, _ = make_facts()
    url = FACTS_URL.format(cik=1234)
    sec, t = make_sec({url: [(429, {}), (200, facts)]})
    assert sec.company_facts(1234)["entityName"] == "Example Corp"
    assert len(t.calls) == 2 and t.calls[0][1]["User-Agent"] == "test-app test@example.com"
    assert sec.sleeps  # backed off / paced between requests
    sec.company_facts(1234)  # served from cache
    assert len(t.calls) == 2


def test_sec_client_does_not_retry_404(make_sec):
    sec, t = make_sec({FACTS_URL.format(cik=9): [(404, {})]})
    with pytest.raises(SecError):
        sec.company_facts(9)
    assert len(t.calls) == 1


def test_sec_tickers_parses_columnar_file(make_sec):
    sec, _ = make_sec({TICKERS_URL: [(200, {"fields": ["cik", "name", "ticker", "exchange"],
                                            "data": [[1, "A Inc", "A", "NYSE"]]})]})
    assert sec.tickers() == [{"cik": 1, "name": "A Inc", "ticker": "A", "exchange": "NYSE"}]


# ---------------------------------------------------------------- security master
def test_security_master_identifiers_and_matching():
    rows, summary = build_security_master(INSTRUMENTS, SEC_TICKERS)
    by = {r["isin"]: r for r in rows}
    assert len(rows) == 5 and summary["excluded_by_type"] == {"ETF": 1}
    assert by["US0000000001"]["company_id"] == "SEC:1234" and by["US0000000001"]["sec_match"] == "high"
    renamed = by["US0000000002"]
    assert renamed["symbol"] == "NEWT" and renamed["t212_ticker"] == "OLDT_US_EQ" and renamed["cik"] == 2222
    assert by["US0846707026"]["cik"] == 1067983  # BRK.B -> SEC's BRK-B
    mism = by["US0000000003"]
    assert mism["sec_match"] == "low" and mism["company_id"] == "ISIN:US0000000003"
    assert by["GB00BGDT3G23"]["company_id"] == "ISIN:GB00BGDT3G23" and by["GB00BGDT3G23"]["cik"] is None
    assert summary["sec_linked_low_needs_review"] == 1


def test_cross_listed_isin_is_one_company_with_stable_listings(store):
    """Regression (found on the live universe 2026-10-14): one ISIN listed in CAD and USD.
    Keying rows by ISIN made the record flip between listings on every sync."""
    cross = [
        {"ticker": "STN_CA_EQ", "type": "STOCK", "isin": "CA85472N1096", "currencyCode": "CAD",
         "shortName": "STN", "name": "Stantec"},
        {"ticker": "STN_US_EQ", "type": "STOCK", "isin": "CA85472N1096", "currencyCode": "USD",
         "shortName": "STN", "name": "Stantec"},
    ]
    sec = [{"cik": 1131383, "name": "STANTEC INC", "ticker": "STN", "exchange": "NYSE"}]
    rows, summary = build_security_master(cross, sec)
    assert {r["company_id"] for r in rows} == {"SEC:1131383"}
    assert summary["stocks_in_master"] == 2 and summary["unique_isins"] == 1 and summary["companies"] == 1
    sync_security_master(store, cross, sec)
    sync_security_master(store, list(reversed(cross)), sec)  # order must not matter
    assert len(store.securities.read()) == 2


@pytest.mark.parametrize("t212,sec,ok", [
    ("Lowe's", "LOWES COMPANIES INC", True), ("Brink's", "BRINKS CO", True),
    ("America's Car-Mart", "AMERICAS CARMART INC", True), ("RealReal", "TheRealReal, Inc.", True),
    ("Eocene", "Galmed Pharmaceuticals Ltd.", False), ("Cia Cervecerias Unidas", "UNITED BREWERIES CO INC", False),
])
def test_name_match_normalisation(t212, sec, ok):
    from equity.universe import name_match
    assert name_match(t212, sec) is ok


def test_security_sync_is_idempotent_and_tracks_changes(store):
    s1 = sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    n = len(store.securities.read())
    s2 = sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    assert s1["added"] == 5 and s2["added"] == s2["changed"] == s2["removed"] == 0
    assert len(store.securities.read()) == n
    # Removal is recorded, not deleted; reappearance and A->B->A changes are recorded too.
    sync_security_master(store, INSTRUMENTS[1:], SEC_TICKERS)
    assert resolve(store, isin="US0000000001") is None
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    assert resolve(store, isin="US0000000001")["symbol"] == "EXMP"
    renamed = copy.deepcopy(INSTRUMENTS)
    renamed[0]["name"] = "Example Renamed"
    sync_security_master(store, renamed, SEC_TICKERS)
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    assert resolve(store, isin="US0000000001")["name"] == "Example"
    hist = [r for r in store.securities.read() if r["isin"] == "US0000000001"]
    assert len(hist) == 5  # v1, absent, back, renamed, back again


# ---------------------------------------------------------------- fundamentals
def test_fcf_per_share_and_growth_are_exact():
    facts, ends, rev = make_facts()
    a = analyse(facts, TODAY)
    last = ends[-1]
    y = a["years"][last]
    assert y["revenue"]["v"] == pytest.approx(rev[last])     # 10-Q and 3-month values ignored
    assert y["revenue"]["a"] and y["revenue"]["f"] and y["revenue"]["c"] == "Revenues"
    d = a["derived"][last]
    assert d["fcf"] == pytest.approx(rev[last] * 0.25)
    assert d["fcf_per_share"] == pytest.approx(rev[last] * 0.25 / 95)
    s = a["summary"]
    expected = cagr(rev[ends[0]] * 0.25 / 100, rev[last] * 0.25 / 95, 5)
    assert s["fcf_per_share_cagr_5y"] == pytest.approx(expected)
    assert s["revenue_cagr_5y"] == pytest.approx(0.10)
    assert s["share_change_cagr_3y"] < 0  # net buybacks
    assert s["gross_margin"] == pytest.approx(0.6) and s["fcf_margin"] == pytest.approx(0.25)
    # ROIC: op income * (1 - 0.2) / (equity + debt - cash)
    assert s["roic"] == pytest.approx(rev[last] * 0.25 * 0.8 / 1000)
    assert a["confidence"] == "high" and a["flags"] == []


def test_restatement_uses_latest_keeps_original_and_flags():
    facts, ends, rev = make_facts()
    ocf = facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"]
    target = ends[-2]
    ocf.append({"start": f"{int(target[:4]) - 1}{target[4:]}", "end": target, "val": rev[target] * 0.2,
                "accn": "restate", "form": "10-K", "filed": "2026-09-01"})
    a = analyse(facts, TODAY)
    v = a["years"][target]["ocf"]
    assert v["v"] == pytest.approx(rev[target] * 0.2) and v["orig"] == pytest.approx(rev[target] * 0.3)
    assert v["a"] == "restate" and f"restated:ocf:{target}" in a["flags"]


def test_missing_capex_gives_no_fcf_and_low_confidence():
    facts, ends, _ = make_facts(capex=False)
    a = analyse(facts, TODAY)
    assert a["derived"][ends[-1]]["fcf"] is None and a["summary"]["fcf_per_share"] is None
    assert "missing:capex" in a["flags"] and a["confidence"] == "low"


def test_stale_and_short_history_flags():
    facts, _, _ = make_facts(n_years=3)
    a = analyse(facts, date(2028, 1, 1))
    assert "stale_annual_data" in a["flags"] and "short_history" in a["flags"]
    assert a["summary"]["fcf_per_share_cagr_5y"] is None  # not enough history: no number invented


def test_cagr_refuses_non_positive_endpoints():
    assert cagr(-1, 5, 3) is None and cagr(1, 0, 3) is None and cagr(1, 8, 3) == pytest.approx(1.0)


def test_concept_fallback_and_switch_flag():
    facts, ends, _ = make_facts(revenue_concept="SalesRevenueNet")
    g = facts["facts"]["us-gaap"]
    new = g["SalesRevenueNet"]["units"]["USD"]
    g["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [
        dict(e) for e in new if e["end"] >= ends[3] and e["form"] == "10-K" and e["accn"] not in ("q4",)]}}
    a = analyse(facts, TODAY)
    assert a["years"][ends[0]]["revenue"]["c"] == "SalesRevenueNet"
    assert a["years"][ends[-1]]["revenue"]["c"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert "concept_switch:revenue" in a["flags"]


# ---------------------------------------------------------------- pipeline
def test_pipeline_requires_reason_evidence_and_allowed_path(store):
    with pytest.raises(pipeline.TransitionError):
        pipeline.transition(store, "SEC:1", "discovered", "", ["x"], "t")
    with pytest.raises(pipeline.TransitionError):
        pipeline.transition(store, "SEC:1", "discovered", "r", [" "], "t")
    with pytest.raises(pipeline.TransitionError):
        pipeline.transition(store, "SEC:1", "watchlist", "r", ["e"], "t")  # must start at discovered
    pipeline.discover(store, "SEC:1", "Ex", "manual", "seed", ["url"], "t")
    assert pipeline.discover(store, "SEC:1", "Ex", "manual", "seed", ["url"], "t") is None
    with pytest.raises(pipeline.TransitionError):
        pipeline.transition(store, "SEC:1", "candidate", "r", ["e"], "t")


def test_candidate_gate_and_reversible_history(store):
    cid = "SEC:1"
    pipeline.discover(store, cid, "Ex", "manual", "seed", ["url"], "t")
    for st in ("research_queue", "qualified", "watchlist"):
        pipeline.transition(store, cid, st, "ok", ["snap:1"], "t")
    with pytest.raises(pipeline.TransitionError, match="bear case"):
        pipeline.transition(store, cid, "candidate", "cheap", ["snap:1"], "t",
                            {"bear_case_recorded": False, "data_confidence": "high"})
    with pytest.raises(pipeline.TransitionError, match="confidence"):
        pipeline.transition(store, cid, "candidate", "cheap", ["snap:1"], "t",
                            {"bear_case_recorded": True, "data_confidence": "low"})
    with pytest.raises(pipeline.TransitionError, match="industry"):  # unclassified counts as unsupported
        pipeline.transition(store, cid, "candidate", "cheap", ["snap:1"], "t",
                            {"bear_case_recorded": True, "data_confidence": "medium"})
    pipeline.transition(store, cid, "candidate", "cheap", ["snap:1"], "t",
                        {"bear_case_recorded": True, "data_confidence": "medium", "industry_supported": True})
    pipeline.transition(store, cid, "rejected", "thesis failed", ["10-Q accn"], "t")
    pipeline.transition(store, cid, "research_queue", "material change: new CEO", ["8-K accn"], "t")
    h = pipeline.history(store, cid)
    assert [t["to"] for t in h] == ["discovered", "research_queue", "qualified", "watchlist", "candidate",
                                    "rejected", "research_queue"]
    assert pipeline.current_status(store, cid) == "research_queue"


# ---------------------------------------------------------------- ingest + snapshots + index
def test_snapshot_written_only_on_change_and_requires_verified_link(store, make_sec):
    facts, ends, rev = make_facts()
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    sec, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)]})
    exmp = resolve(store, symbol="EXMP")
    s1, w1 = ingest_company(store, sec, exmp, TODAY)
    s2, w2 = ingest_company(store, sec, exmp, TODAY)
    assert w1 and not w2 and s1["rid"] == s2["rid"]
    assert s1["source_url"].endswith("CIK0000001234.json") and s1["years"]
    assert store.methods.read()[0]["methods"]["fcf"] and s1["industry_template"] == "industrial"
    # A new filing produces a new snapshot linked to the previous one.
    facts2 = copy.deepcopy(facts)
    facts2["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2025-09-30", "end": "2026-09-30", "val": 2000.0, "accn": "new", "form": "10-K",
         "filed": "2026-10-10"})
    sec2, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts2)]})
    sec2.cache_dir = sec2.cache_dir / "fresh"
    s3, w3 = ingest_company(store, sec2, exmp, TODAY)
    assert w3 and s3["previous_snapshot"] == s1["rid"]
    with pytest.raises(ValueError, match="no verified SEC link"):
        ingest_company(store, sec, resolve(store, symbol="MISM"), TODAY)


def test_index_search_reflects_status_and_metrics(store, make_sec, tmp_path):
    facts, _, _ = make_facts()
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    sec, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)]})
    ingest_company(store, sec, resolve(store, symbol="EXMP"), TODAY)
    pipeline.discover(store, "SEC:1234", "Example", "manual", "seed", ["url"], "t")
    db = sqlite3.connect(index.build(store, tmp_path / "idx.sqlite"))
    row = db.execute("SELECT status, confidence, roic FROM companies WHERE company_id='SEC:1234'").fetchone()
    assert row[0] == "discovered" and row[1] == "high" and row[2] > 0.2
    assert db.execute("SELECT COUNT(*) FROM securities").fetchone()[0] == 5


def _split_company():
    """10-Ks report 3 years each. 4:1 split during FY2021, 10:1 during FY2024 (NVIDIA-like).
    True economic share count: 1000 'current' shares every year, so FCF/share is flat."""
    g = {"Revenues": {"units": {"USD": []}}, "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": []}},
         "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": []}},
         "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": []}},
         "EarningsPerShareDiluted": {"units": {"USD/shares": []}}}
    basis_at_filing = {2019: 40, 2020: 40, 2021: 10, 2022: 10, 2023: 10, 2024: 1, 2025: 1}  # divide by
    for fy in range(2019, 2026):
        accn, filed = f"A{fy}", f"{fy + 1}-02-20"
        for yr in (fy, fy - 1, fy - 2):
            if yr < 2017:
                continue
            per = {"start": f"{yr - 1}-12-31", "end": f"{yr}-12-31", "accn": accn, "form": "10-K", "filed": filed}
            g["Revenues"]["units"]["USD"].append({**per, "val": 1000.0})
            g["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"].append({**per, "val": 300.0})
            g["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"].append({**per, "val": 100.0})
            g["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"].append(
                {**per, "val": 1000.0 / basis_at_filing[fy]})
            g["EarningsPerShareDiluted"]["units"]["USD/shares"].append({**per, "val": 0.1 * basis_at_filing[fy]})
    return {"entityName": "Splitco", "facts": {"us-gaap": g}}


def test_share_splits_are_put_on_current_basis():
    a = analyse(_split_company(), date(2026, 6, 1))
    for end, row in a["years"].items():
        assert row["shares_diluted"]["v"] == pytest.approx(1000.0), end
        assert row["eps_diluted"]["v"] == pytest.approx(0.1), end
        assert a["derived"][end]["fcf_per_share"] == pytest.approx(0.2), end
    assert a["years"]["2017-12-31"]["shares_diluted"]["split_adj"] == pytest.approx(40)
    assert a["years"]["2017-12-31"]["shares_diluted"]["v_as_filed"] == pytest.approx(25)
    assert a["summary"]["fcf_per_share_cagr_5y"] == pytest.approx(0.0)
    assert "share_split_adjusted" in a["flags"]
    assert not [f for f in a["flags"] if f.startswith(("restated:shares", "restated:eps", "split_basis"))]


def test_split_factor_does_not_swallow_ordinary_restatements():
    from equity.fundamentals import _split_factor
    assert _split_factor(4.01) == 4 and _split_factor(0.1) == pytest.approx(0.1) and _split_factor(1.2) == 1.0


def test_index_prefers_sec_verified_primary_listing(store, tmp_path):
    extra = INSTRUMENTS + [{"ticker": "EXMPd_EQ", "type": "STOCK", "isin": "US0000000001", "currencyCode": "EUR",
                            "shortName": "AAA", "name": "Example"}]  # German line, alphabetically first
    sync_security_master(store, extra, SEC_TICKERS)
    pipeline.discover(store, "SEC:1234", "Example", "manual", "seed", ["url"], "t")
    db = sqlite3.connect(index.build(store, tmp_path / "idx.sqlite"))
    assert db.execute("SELECT symbol, primary_listing FROM companies WHERE company_id='SEC:1234'").fetchone() == \
        ("EXMP", "EXMP_US_EQ")


def test_crosscheck_compare_signs_dates_and_conflicts():
    from equity.crosscheck import compare
    snap = {"summary": {"latest_fy_end": "2025-09-27"},
            "years": {"2025-09-27": {"revenue": {"v": 100.0, "c": "Revenues"}, "capex": {"v": 10.0, "c": "X"},
                                     "ocf": {"v": 50.0, "c": "Y"}}}}
    yahoo = {"annualTotalRevenue": {"2025-09-30": 101.0},        # 3 days apart: same fiscal year
             "annualCapitalExpenditure": {"2025-09-30": -10.0},  # Yahoo reports capex as negative
             "annualOperatingCashFlow": {"2025-09-30": 60.0},
             "annualDilutedAverageShares": {"2025-09-30": 7.0}}
    st = {r["metric"]: r["status"] for r in compare(snap, yahoo)}
    assert st == {"revenue": "agree", "capex": "agree", "ocf": "CONFLICT", "shares_diluted": "missing_in_sec"}
