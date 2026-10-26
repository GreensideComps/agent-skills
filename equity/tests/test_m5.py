"""Milestone 5: paper portfolio - logged recommendations, simulated fills, benchmark, monthly cadence."""
from __future__ import annotations

import pytest

from equity import paper

CFG = {**paper.load_config(), "max_positions": 2, "min_total_score": 50, "starting_cash": 1000.0}
COST = 0.0025


def _screen(as_of, ranked):
    """ranked: [(company_id, total)] in rank order."""
    res = [{"company_id": c, "entity_name": c, "total": t, "rank": i + 1, "scores": {}} for i, (c, t) in enumerate(ranked)]
    res.append({"company_id": "SEC:low", "entity_name": "low", "total": 90.0, "rank": None, "scores": {}})
    return {"rid": f"screen:{as_of}", "as_of": as_of, "results": res}


def _px(as_of, **closes):
    d = {c: {"close": v, "date": as_of, "rid": f"{c}:{as_of}"} for c, v in closes.items()}
    d["BENCH:SPY"] = {"close": closes.get("spy", 100.0), "date": as_of, "rid": f"spy:{as_of}"}
    return d


def test_first_rebalance_funds_both_books_and_logs_recommendations_first(store):
    rec = _screen("2026-10-14", [("A", 80.0), ("B", 70.0), ("C", 65.0)])
    out = paper.rebalance(store, rec, _px("2026-10-14", A=10.0, B=20.0, C=5.0), CFG,
                          valuations={"A": {"implied_growth_5y": 0.1}})
    assert out["rebalanced"] and out["targets"] == ["A", "B"]           # top 2; unranked 'low' ignored
    st = paper.state(store, "portfolio")
    assert st["positions"]["A"] * 10.0 * (1 + COST) == pytest.approx(1000 * (1 - COST) / 2)
    assert st["cash"] >= 0 and st["cash"] == pytest.approx(1000 * COST, rel=1e-6)
    recs = {r["company_id"]: r for r in store.recommendations.read()}
    assert recs["A"]["decision_price"] == 10.0 and recs["A"]["implied_growth_5y"] == 0.1
    assert recs["A"]["action"] == "buy" and "logged before outcome" in recs["A"]["basis"]
    b = paper.state(store, "benchmark")
    assert b["positions"]["BENCH:SPY"] == pytest.approx(1000 / (100 * (1 + COST)))
    fills = [t for t in store.paper.read() if t["kind"] == "buy"]
    assert all(t["fill_price"] == pytest.approx(t["decision_price"] * (1 + COST)) for t in fills)


def test_rebalance_is_monthly_and_idempotent(store):
    rec = _screen("2026-10-14", [("A", 80.0), ("B", 70.0)])
    paper.rebalance(store, rec, _px("2026-10-14", A=10.0, B=20.0), CFG)
    n = len(store.paper.read())
    later = _screen("2026-10-20", [("C", 99.0), ("D", 98.0)])
    assert paper.rebalance(store, later, _px("2026-10-20", C=1.0, D=1.0), CFG)["rebalanced"] is False
    assert len(store.paper.read()) == n
    nov = _screen("2026-11-03", [("A", 80.0), ("C", 75.0)])
    out = paper.rebalance(store, nov, _px("2026-11-03", A=12.0, B=18.0, C=4.0), CFG)
    assert out["rebalanced"] and set(paper.state(store, "portfolio")["positions"]) == {"A", "C"}
    sells = [t for t in store.paper.read() if t["kind"] == "sell" and t["company_id"] == "B"]
    assert sells and sells[0]["fill_price"] == pytest.approx(18.0 * (1 - COST))
    assert any(r["action"] == "sell" and r["company_id"] == "B" for r in store.recommendations.read())
    assert paper.state(store, "portfolio")["cash"] >= -1e-9
    # Benchmark is bought once and held.
    assert len([t for t in store.paper.read() if t["book"] == "benchmark" and t["kind"] == "buy"]) == 1


def test_mark_and_excess_return(store):
    rec = _screen("2026-10-14", [("A", 80.0), ("B", 70.0)])
    paper.rebalance(store, rec, _px("2026-10-14", A=10.0, B=20.0), CFG)
    m = paper.mark(store, _px("2026-10-15", A=11.0, B=22.0, spy=101.0), "2026-10-15")
    st = paper.state(store, "portfolio")
    assert m["portfolio"]["nav"] == pytest.approx(st["cash"] + st["positions"]["A"] * 11 + st["positions"]["B"] * 22)
    assert m["excess_return"] == pytest.approx(m["portfolio"]["nav"] / m["benchmark"]["nav"] - 1)
    assert m["excess_return"] > 0
    md = paper.report(store, CFG)
    assert "Excess" in md and "Dividends excluded" in md


def test_stale_or_missing_price_refuses_to_trade(store):
    rec = _screen("2026-10-14", [("A", 80.0), ("B", 70.0)])
    prices = _px("2026-10-14", A=10.0)
    with pytest.raises(paper.PaperError, match="B"):
        paper.rebalance(store, rec, prices, CFG)
    assert store.paper.read() == [] and store.recommendations.read() == []  # nothing half-written
    old = _px("2026-09-01", A=10.0, B=20.0)
    with pytest.raises(paper.PaperError):
        paper.rebalance(store, rec, old, CFG)


def test_mandate_is_recorded_in_config():
    cfg = paper.load_config()
    assert cfg["method_version"] == "paper-1.1" and cfg["benchmark"]["symbol"] == "SPY"
    assert cfg["primary_benchmark"]["symbol"] == "VWRP.L" and "D-T14" in cfg["primary_benchmark"]["decision"]
    assert cfg["costs"]["fx_bps"] == 15  # Trading 212's FX fee on a GBP account


# paper-1.1 (D-T14): VWRP primary benchmark beside SPY, history kept.
def _vw(d, as_of, gbp=100.0, fx=1.25, cur="GBP"):
    d["BENCH:VWRP.L"] = {"close": gbp, "date": as_of, "rid": f"vwrp:{as_of}", "currency": cur}
    d["BENCH:GBPUSD=X"] = {"close": fx, "date": as_of, "rid": f"fx:{as_of}", "currency": "USD"}
    return d


def test_vwrp_book_starts_at_first_priced_mark_and_keeps_spy(store):
    assert CFG["method_version"] == "paper-1.1" and CFG["benchmark"]["symbol"] == "SPY"
    paper.rebalance(store, _screen("2026-10-14", [("A", 80.0), ("B", 70.0)]), _px("2026-10-14", A=10.0, B=20.0), CFG)
    m1 = paper.mark(store, _px("2026-10-15", A=11.0, B=22.0), "2026-10-15", CFG)   # no VWRP price yet
    assert m1["benchmark_vwrp"]["status"] == "not started" and "excess_return_vwrp" not in m1
    assert "excess_return" in m1
    m2 = paper.mark(store, _vw(_px("2026-10-16", A=11.0, B=22.0), "2026-10-16"), "2026-10-16", CFG)
    v = m2["benchmark_vwrp"]
    assert v["status"] == "marked" and v["start"] == "2026-10-16" and v["usd"] == pytest.approx(125.0)
    assert v["start_nav"] == pytest.approx(m2["portfolio"]["nav"])
    assert m2["excess_return_vwrp"] == pytest.approx(COST)  # only the entry cost
    m3 = paper.mark(store, _vw(_px("2026-10-19", A=11.0, B=22.0), "2026-10-19", gbp=110.0), "2026-10-19", CFG)
    assert m3["benchmark_vwrp"]["nav"] / v["nav"] == pytest.approx(1.10)
    assert len([t for t in store.paper.read() if t["book"] == "benchmark_vwrp" and t["kind"] == "fund"]) == 1
    md = paper.report(store, CFG)
    assert "Primary benchmark: VWRP" in md and "Secondary benchmark (SPY)" in md and "biased against" in md
    assert "Started 2026-10-16" in md


def test_vwrp_pence_quote_and_bad_currency(store):
    usd, how = paper.primary_price_usd(_vw({}, "2026-10-16", gbp=14240.0, cur="GBp"), CFG, "2026-10-16")
    assert usd == pytest.approx(142.40 * 1.25)
    assert paper.primary_price_usd(_vw({}, "2026-10-16", cur="EUR"), CFG, "2026-10-16")[1]["status"] == "unpriced"
    assert "stale" in paper.primary_price_usd(_vw({}, "2026-09-01"), CFG, "2026-10-16")[1]["reason"]


def test_paper_10_records_are_not_restated(store):
    paper.rebalance(store, _screen("2026-10-14", [("A", 80.0)]), _px("2026-10-14", A=10.0),
                    {**CFG, "method_version": "paper-1.0"})
    before = list(store.paper.read())
    paper.mark(store, _vw(_px("2026-10-16", A=11.0), "2026-10-16"), "2026-10-16", CFG)
    after = store.paper.read()
    assert after[:len(before)] == before and all(t["method_version"] == "paper-1.0" for t in before)


def test_vwrp_review_findings_unpriced_future_and_same_day(store):
    paper.rebalance(store, _screen("2026-10-14", [("A", 80.0), ("B", 70.0)]), _px("2026-10-14", A=10.0, B=20.0), CFG)
    m = paper.mark(store, _vw(_px("2026-10-15", A=11.0), "2026-10-15"), "2026-10-15", CFG)   # B unpriced
    assert m["benchmark_vwrp"]["status"] == "not started" and "unpriced" in m["benchmark_vwrp"]["reason"]
    m = paper.mark(store, _vw(_px("2026-10-15", A=11.0, B=22.0), "2026-10-15"), "2026-10-15", CFG)  # same day again
    assert m["benchmark_vwrp"]["status"] == "not started" and "already marked" in m["benchmark_vwrp"]["reason"]
    assert not [t for t in store.paper.read() if t["book"] == "benchmark_vwrp"]
    future = _vw(_px("2026-10-16", A=11.0, B=22.0), "2026-10-17")
    assert "after" in paper.primary_price_usd(future, CFG, "2026-10-16")[1]["reason"]
    skew = _vw({}, "2026-10-16")
    skew["BENCH:GBPUSD=X"]["date"] = "2026-10-13"
    assert "apart" in paper.primary_price_usd(skew, CFG, "2026-10-16")[1]["reason"]
    m = paper.mark(store, _vw(_px("2026-10-16", A=11.0, B=22.0), "2026-10-16"), "2026-10-16", CFG)
    assert m["benchmark_vwrp"]["status"] == "marked" and m["excess_return_vwrp"] == pytest.approx(COST)
