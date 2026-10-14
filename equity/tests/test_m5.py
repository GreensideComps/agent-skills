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
    assert cfg["method_version"] == "paper-1.0" and cfg["benchmark"]["symbol"] == "SPY"
    assert cfg["costs"]["fx_bps"] == 15  # Trading 212's FX fee on a GBP account
