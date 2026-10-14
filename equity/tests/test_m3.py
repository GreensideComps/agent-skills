"""Milestone 3: prices, valuation inputs, the five scores, gates and ranking."""
from __future__ import annotations

import json
from datetime import date

import pytest
from conftest import INSTRUMENTS, SEC_TICKERS, make_facts

from equity import screener
from equity.fundamentals import analyse, shares_outstanding
from equity.ingest import ingest_company, last_snapshot, resolve
from equity.prices import latest_prices, parse_chart, update_prices
from equity.sec import FACTS_URL
from equity.universe import sync_security_master

TODAY = date(2026, 10, 14)
CFG = screener.load_config()


def chart(close, ts=1791936000, cur="USD"):  # 2026-10-14 00:00 UTC
    return json.dumps({"chart": {"result": [{"meta": {"currency": cur, "exchangeName": "NMS"}, "timestamp": [ts - 86400, ts],
                                             "indicators": {"quote": [{"close": [close - 1, close]}]}}]}}).encode()


def test_scale_is_linear_clipped_and_handles_inverse():
    assert screener.scale(0.10, 0.0, 0.20) == pytest.approx(50)
    assert screener.scale(0.5, 0.0, 0.20) == 100 and screener.scale(-1, 0, 1) == 0
    assert screener.scale(1.5, 3.0, 0.0) == pytest.approx(50)   # lower is better
    assert screener.scale(None, 0, 1) is None


def test_component_reweights_missing_metrics_and_refuses_low_coverage():
    spec = [{"metric": "a", "weight": 0.6, "zero": 0, "full": 1}, {"metric": "b", "weight": 0.4, "zero": 0, "full": 1}]
    c = screener.component(spec, {"a": 0.5, "b": None}, 0.5)
    assert c["score"] == pytest.approx(50) and c["coverage"] == pytest.approx(0.6)
    assert screener.component(spec, {"a": None, "b": 1.0}, 0.5)["score"] is None  # 40% < 50%: no number
    fb = [{"metric": "a", "fallback": "a3", "weight": 1, "zero": 0, "full": 1}]
    assert screener.component(fb, {"a": None, "a3": 0.25}, 0.5)["parts"][0]["metric"] == "a3"


def test_shares_outstanding_sums_classes_and_falls_back():
    facts, ends, _ = make_facts()
    facts["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-07-20", "val": 60, "accn": "q3", "form": "10-Q", "filed": "2026-08-01"},
        {"end": "2026-07-20", "val": 30, "accn": "q3", "form": "10-Q", "filed": "2026-08-01"},  # class B
        {"end": "2026-04-20", "val": 99, "accn": "q2", "form": "10-Q", "filed": "2026-05-01"}]}}}
    so = shares_outstanding(facts, analyse(facts, TODAY)["years"])
    assert so["v"] == 90 and so["classes"] == 2 and so["a"] == "q3"
    del facts["facts"]["dei"]
    a = analyse(facts, TODAY)
    assert a["shares_outstanding"]["c"].startswith("proxy:") and a["shares_outstanding"]["v"] == 95


def _add_d_and_a(facts):
    from conftest import fy
    rev = {e["end"]: e["val"] for e in facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"] if e["form"] == "10-K"
           and e["accn"] != "q4"}
    facts["facts"]["us-gaap"]["DepreciationDepletionAndAmortization"] = fy({}, "USD", {e: v * 0.04 for e, v in rev.items()})


def _scored(store, make_sec, close=50.0, cur="USD", mutate=None):
    facts, ends, rev = make_facts()
    _add_d_and_a(facts)
    if mutate:
        mutate(facts)
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    sec, _ = make_sec({FACTS_URL.format(cik=1234): [(200, facts)]})
    ingest_company(store, sec, resolve(store, symbol="EXMP"), TODAY)
    update_prices(store, [resolve(store, symbol="EXMP")], get=lambda url: chart(close, cur=cur), sleep=lambda s: None)
    snap = last_snapshot(store, "SEC:1234")
    return screener.score_company(snap, latest_prices(store)["SEC:1234"], CFG, TODAY), snap, rev, ends


def test_valuation_and_full_score_for_a_clean_company(store, make_sec):
    r, snap, rev, ends = _scored(store, make_sec)
    last = ends[-1]
    mcap = 50.0 * 95  # fallback share count: latest diluted weighted shares
    v = r["valuation"]
    assert v["market_cap"] == pytest.approx(mcap)
    assert v["fcf_yield"] == pytest.approx(rev[last] * 0.25 / mcap)
    assert v["ebit_yield"] == pytest.approx(rev[last] * 0.25 / (mcap + 300 - 200))
    assert r["eligible"] and not r["failed_gates"]
    w = CFG["weights"]
    assert r["total"] == pytest.approx(sum(w[c] * r["scores"][c] for c in w) / 100)
    assert r["scores"]["growth"] is not None and r["data_confidence"] == "high"


def test_currency_mismatch_or_stale_price_blocks_ranking(store, make_sec):
    r, *_ = _scored(store, make_sec, cur="GBp")
    g = {x["gate"]: x for x in r["gates"]}
    assert g["valuation_available"]["result"] == "fail" and "currency_mismatch" in g["valuation_available"]["detail"]
    assert not r["eligible"] and r["valuation"]["market_cap"] is None
    snap = last_snapshot(store, "SEC:1234")
    old = {**latest_prices(store)["SEC:1234"], "currency": "USD", "date": "2026-09-01"}
    r2 = screener.score_company(snap, old, CFG, TODAY)
    assert "stale_price" in next(x for x in r2["gates"] if x["gate"] == "valuation_available")["detail"]


def test_foreign_filer_valuation_is_unavailable_not_guessed(store, make_sec):
    def to_20f(facts):
        for node in facts["facts"]["us-gaap"].values():
            for entries in node["units"].values():
                for e in entries:
                    e["form"] = "20-F" if e["form"] == "10-K" else e["form"]
    r, *_ = _scored(store, make_sec, mutate=to_20f)
    assert "adr_ratio_unknown" in next(x for x in r["gates"] if x["gate"] == "valuation_available")["detail"]
    assert r["valuation"]["fcf_yield"] is None and not r["eligible"]


def test_gates_explain_failures(store, make_sec):
    def leverage_and_dilution(facts):
        g = facts["facts"]["us-gaap"]
        for e in g["LongTermDebt"]["units"]["USD"]:
            e["val"] = 50_000.0
        for i, e in enumerate(sorted(g["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"],
                                     key=lambda e: e["end"])):
            e["val"] = 100 * 1.1 ** i
    r, *_ = _scored(store, make_sec, mutate=leverage_and_dilution)
    g = {x["gate"]: x for x in r["gates"]}
    assert g["leverage"]["result"] == "fail" and "max 4.0" in g["leverage"]["detail"]
    assert g["dilution"]["result"] == "fail" and "+10.0%/yr" in g["dilution"]["detail"]
    assert set(r["failed_gates"]) >= {"leverage", "dilution"} and not r["eligible"]


def test_unsupported_industry_is_scored_but_never_ranked(store, make_sec):
    r, snap, *_ = _scored(store, make_sec)
    bank = {**snap, "screen_supported": False, "industry_template": "bank"}
    rb = screener.score_company(bank, latest_prices(store)["SEC:1234"], CFG, TODAY)
    assert "industry_supported" in rb["failed_gates"] and not rb["eligible"]


def test_run_ranks_only_eligible_records_once_and_reports(store, make_sec):
    _scored(store, make_sec)
    rec = screener.run(store, CFG, TODAY)
    assert rec["companies"] == 1 and rec["eligible"] == 1 and rec["results"][0]["rank"] == 1
    assert rec["weights"] == CFG["weights"] and rec["method_version"] == "screen-1.0"
    screener.run(store, CFG, TODAY)
    assert len(store.screens.read()) == 1  # same inputs, same day: one record
    md = screener.report(rec)
    assert "| 1 | Example Corp |" in md and "passed every gate" in md
    stored, full = screener.explain(store, "SEC:1234", CFG)
    assert "components" not in stored and full["config_matches_run"]
    assert full["total"] == pytest.approx(stored["total"]) and full["components"]["quality"]["parts"]


def test_price_parsing_and_idempotent_ledger(store):
    p = parse_chart(chart(12.5))
    assert p == {"close": 12.5, "date": "2026-10-14", "currency": "USD", "exchange": "NMS"}
    sync_security_master(store, INSTRUMENTS, SEC_TICKERS)
    s = resolve(store, symbol="BRK.B")
    seen = []
    res = update_prices(store, [s], get=lambda url: seen.append(url) or chart(400.0), sleep=lambda x: None)
    assert res["written"] == 1 and "BRK-B" in seen[0]
    assert update_prices(store, [s], get=lambda url: chart(400.0), sleep=lambda x: None)["written"] == 0
    bad = update_prices(store, [s], get=lambda url: b'{"chart":{"result":null}}', sleep=lambda x: None)
    assert bad["written"] == 0 and bad["failed"]


def test_weights_are_the_owner_baseline():
    assert CFG["weights"] == {"fcf_per_share": 30, "quality": 25, "growth": 20, "valuation": 20, "risk_fit": 5}
    for name, spec in CFG["components"].items():
        assert sum(s["weight"] for s in spec) == pytest.approx(1.0), name


def test_leverage_is_unknown_without_ebitda_and_fails_on_negative_ebitda(store, make_sec):
    r, snap, *_ = _scored(store, make_sec)
    fy = snap["summary"]["latest_fy_end"]
    no_e = {**snap, "summary": {**snap["summary"], "net_debt": 100.0, "net_debt_to_ebitda": None},
            "derived": {fy: {}}}
    g = {x["gate"]: x for x in screener.score_company(no_e, None, CFG, TODAY)["gates"]}
    assert g["leverage"]["result"] == "unknown"
    neg = {**no_e, "derived": {fy: {"ebitda": -5.0}}}
    g = {x["gate"]: x for x in screener.score_company(neg, None, CFG, TODAY)["gates"]}
    assert g["leverage"]["result"] == "fail" and "non-positive" in g["leverage"]["detail"]
